"""Generate local Redmint lures as mono 24 kHz PCM."""

from contextlib import redirect_stdout
from io import BytesIO
import os
from pathlib import Path
from random import Random, choice, sample
from shutil import which
from struct import Struct
import subprocess
import sys
from typing import BinaryIO
import wave

import numpy as np
from scipy.signal import butter, resample_poly, sosfiltfilt


PROJECT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ.get("REDMINT_VOICE_RUNTIME", PROJECT / "Playtest/.local/CosyVoice"))
OUTPUT_RATE = 24_000
REFERENCE_RATE = 16_000
PCM_BYTES_PER_SAMPLE = 2
MAX_CLIP_SECONDS = 15
MAX_PHRASE_BYTES = 720
MIN_LIVE_SAMPLE_BYTES = 5 * REFERENCE_RATE * PCM_BYTES_PER_SAMPLE
MAX_LIVE_SAMPLE_BYTES = 8 * REFERENCE_RATE * PCM_BYTES_PER_SAMPLE
# The C# worker writes four little-endian integers before the UTF-8 phrase and live PCM.
REQUEST_HEADER = Struct("<IIII")

PHRASES = (
    "Hold up who's here?",
    "Gimme a sec.",
    "What the hell?",
    "Do you know where the exit is?",
    "I'm lost.",
)


def loudness_envelope(audio: np.ndarray, cutoff_hz: float) -> np.ndarray:
    """Estimate the local RMS level of a mono signal at the output sample rate."""
    low_pass = butter(2, cutoff_hz, fs=OUTPUT_RATE, output="sos")
    smoothed_power = sosfiltfilt(low_pass, audio ** 2)
    return np.sqrt(np.maximum(0, smoothed_power))


def decode_wav(path: Path, sample_rate: int, max_seconds: int) -> np.ndarray:
    """Decode a WAV to mono float samples at the requested rate."""
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-t", str(max_seconds),
            "-ar", str(sample_rate), "-ac", "1", "-f", "f32le", "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype="<f4")


def mix_growls(voice: np.ndarray) -> np.ndarray:
    """Crossfade growl clips and shape their loudness to follow the spoken syllables."""
    files = sorted((RUNTIME / "Growls").glob("*.wav"))
    if not files:
        files = sorted((RUNTIME / "Growls").glob("Growl*.pcm"))
    if not files:
        files = sorted((PROJECT / "Audio/Voice").glob("Growl*.pcm"))
    if not files:
        return voice

    duration = len(voice) / OUTPUT_RATE
    count = min(len(files), max(1, round(duration / 1.2)))
    time = np.arange(len(voice)) / OUTPUT_RATE
    crossfade_seconds = 0.18
    boundaries = [
        np.clip(
            (time - index * duration / count + crossfade_seconds / 2) / crossfade_seconds,
            0,
            1,
        )
        for index in range(1, count)
    ]

    fades = [np.ones_like(time), *boundaries, np.zeros_like(time)]
    growls = np.zeros_like(voice)

    for index, path in enumerate(sample(files, count)):
        if path.suffix == ".pcm":
            raw = np.fromfile(path, dtype="<i2").astype(float) / 32768
        else:
            raw = decode_wav(path, OUTPUT_RATE, max_seconds=20).astype(float)
        if len(raw) < OUTPUT_RATE // 5:
            continue

        band_pass = butter(2, (75, 1450), btype="bandpass", fs=OUTPUT_RATE, output="sos")
        raw = sosfiltfilt(band_pass, raw)
        raw = np.resize(raw, len(voice))
        local_level = loudness_envelope(raw, 4)
        floor = max(np.percentile(local_level, 65) * 0.22, 0.001)
        growls += (fades[index] - fades[index + 1]) * raw / np.maximum(local_level, floor)

    syllables = loudness_envelope(voice, 16)
    threshold = max(np.percentile(syllables, 83) * 0.1, 0.001)
    growls *= syllables * np.clip((syllables - threshold) / (2 * threshold), 0, 1)
    fade_length = min(len(growls), OUTPUT_RATE // 10)
    growls[-fade_length:] *= np.linspace(1, 0, fade_length)
    # Set the growls 4 dB above speech, then leave headroom for consonants in the mix.
    voice_power = np.mean(voice ** 2)
    growl_power = max(np.mean(growls ** 2), 1e-9)
    growls *= np.sqrt(voice_power / growl_power) * 10 ** (4 / 20)
    mixed = voice + growls
    peak = max(np.max(np.abs(mixed)), 0.001)
    return mixed * min(1.0, 0.9 / peak)


def render_lure(voice: np.ndarray) -> bytes:
    """Mix the growls, slow playback to 90%, and encode the result as 24 kHz PCM."""
    mixed = resample_poly(mix_growls(voice.astype(float)), 10, 9)
    if len(mixed) > OUTPUT_RATE * MAX_CLIP_SECONDS:
        raise ValueError("Slowed lure exceeds the 15-second playback limit.")
    return np.rint(np.clip(mixed, -1, 1) * 32767).astype("<i2").tobytes()


def load_models():
    """Load Whisper and CosyVoice once for the worker process."""
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HOME=str(RUNTIME / "hf-cache"),
        MPLCONFIGDIR=str(RUNTIME / "mpl-cache"),
    )
    source = RUNTIME / "source"
    sys.path[:0] = [str(source), str(source / "third_party/Matcha-TTS")]
    import torch
    import whisper
    from cosyvoice.cli.cosyvoice import AutoModel

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    recognizer = whisper.load_model(str(RUNTIME / "whisper-models/base.pt"), device="cpu")
    model = AutoModel(model_dir=str(RUNTIME / "models/Fun-CosyVoice3-0.5B"))
    return torch, recognizer, model


def load_reference(reference: Path | bytes) -> tuple[np.ndarray, str | BytesIO]:
    """Prepare float samples for Whisper and a WAV source for CosyVoice."""
    if isinstance(reference, bytes):
        audio = np.frombuffer(reference, dtype="<i2").astype(np.float32) / 32768
        prompt_audio = BytesIO()
        with wave.open(prompt_audio, "wb") as virtual_wav:
            virtual_wav.setparams(
                (1, PCM_BYTES_PER_SAMPLE, REFERENCE_RATE, 0, "NONE", "not compressed")
            )
            virtual_wav.writeframes(reference)
    else:
        with wave.open(str(reference), "rb") as wav:
            length = wav.getnframes() / wav.getframerate()
        if not 1 <= length <= MAX_CLIP_SECONDS:
            raise ValueError("Choose a reference WAV from 1 to 15 seconds long.")
        audio = decode_wav(reference, REFERENCE_RATE, MAX_CLIP_SECONDS).copy()
        prompt_audio = str(reference)
    if len(audio) < REFERENCE_RATE:
        raise ValueError("Reference is shorter than one second.")
    return audio, prompt_audio


def generate(reference: Path | bytes, phrase: str, models=None) -> bytes:
    """Synthesize one line from a voice reference, reusing loaded models when supplied."""
    torch, recognizer, model = models if models is not None else load_models()
    audio, prompt_audio = load_reference(reference)
    language = os.environ.get("REDMINT_REFERENCE_LANGUAGE", "auto").strip().lower()
    recognition = recognizer.transcribe(
        audio,
        language=None if language in ("auto", "") else language,
        fp16=False,
    )
    transcript = recognition["text"].strip()
    if not transcript:
        raise ValueError("No speech detected in reference.")

    prompt = f"You are a helpful assistant.<|endofprompt|>{transcript}"
    import cosyvoice.cli.frontend as frontend
    original_load = frontend.load_wav
    if isinstance(prompt_audio, BytesIO):
        # CosyVoice reads the reference more than once. Give each reader its own cursor.
        def load_memory(wav, target_sr, *args, **kwargs):
            source = BytesIO(wav.getbuffer()) if wav is prompt_audio else wav
            return original_load(source, target_sr, *args, **kwargs)

        frontend.load_wav = load_memory
    try:
        chunks = model.inference_zero_shot(phrase, prompt, prompt_audio, stream=False)
        voice = torch.cat([part["tts_speech"].cpu() for part in chunks], dim=-1).flatten().numpy()
    finally:
        frontend.load_wav = original_load
    valid_length = OUTPUT_RATE // 10 <= len(voice) <= OUTPUT_RATE * MAX_CLIP_SECONDS
    if model.sample_rate != OUTPUT_RATE or not valid_length:
        raise ValueError("Unexpected clip length or format.")
    return render_lure(voice)


def pick_builtin_phrase(seed: int, index: int) -> str:
    """Pick a phrase from a deterministic shuffle shared by the lobby."""
    order = Random(seed).sample(PHRASES, len(PHRASES))
    return order[index % len(order)]


def valid_live_sample_size(size: int) -> bool:
    """Accept whole PCM samples covering five to eight seconds at 16 kHz."""
    return MIN_LIVE_SAMPLE_BYTES <= size <= MAX_LIVE_SAMPLE_BYTES and size % PCM_BYTES_PER_SAMPLE == 0


def serve(reference_path: str, source: BinaryIO, output: BinaryIO) -> None:
    """Reply with a length-prefixed PCM clip, or a zero length if synthesis fails."""
    models = None
    while header := source.read(REQUEST_HEADER.size):
        seed, index, phrase_size, sample_size = REQUEST_HEADER.unpack(header)
        if phrase_size > MAX_PHRASE_BYTES or (sample_size and not valid_live_sample_size(sample_size)):
            raise ValueError("Invalid voice request size.")
        phrase_bytes = source.read(phrase_size)
        sample = source.read(sample_size)
        if len(phrase_bytes) != phrase_size or len(sample) != sample_size:
            raise EOFError("Incomplete voice request.")
        phrase = phrase_bytes.decode("utf-8").strip() or pick_builtin_phrase(seed, index)
        try:
            with redirect_stdout(sys.stderr):
                if models is None:
                    models = load_models()
                reference = sample if sample else Path(reference_path).resolve(strict=True)
                pcm = generate(reference, phrase, models)
        except Exception as error:
            print(type(error).__name__, file=sys.stderr)
            pcm = b""
        finally:
            sample = reference = None
        output.write(len(pcm).to_bytes(4, "little"))
        output.write(pcm)
        output.flush()
        pcm = None


def check_runtime() -> None:
    """Check that FFmpeg is available and PyTorch can run a CUDA operation."""
    import torch

    if not which("ffmpeg") or not torch.cuda.is_available():
        raise SystemExit("FFmpeg and a compatible CUDA GPU are required for this setup.")
    test = torch.ones(1, device="cuda") + 1
    print(torch.cuda.get_device_name(), test.item())


def run_self_test(reference_path: str) -> None:
    """Generate a sample for setup and report the clip length and peak GPU allocation."""
    pcm = generate(Path(reference_path).resolve(strict=True), PHRASES[0])
    bytes_per_second = OUTPUT_RATE * PCM_BYTES_PER_SAMPLE
    valid_length = bytes_per_second // 10 <= len(pcm) <= bytes_per_second * MAX_CLIP_SECONDS
    if not valid_length or len(pcm) % PCM_BYTES_PER_SAMPLE:
        raise SystemExit("Unexpected test PCM output.")
    print(f"Local synthesis OK: {len(pcm) / bytes_per_second:.2f}s")

    import torch

    if torch.cuda.is_available():
        vram_gib = torch.cuda.max_memory_allocated() / (1024 ** 3)
        print(f"PyTorch peak allocated VRAM: {vram_gib:.2f} GiB")


def run_one_shot(args: list[str], source: BinaryIO, output: BinaryIO) -> None:
    """Handle the positional invocation and the older stdin request formats."""
    phrase = choice(PHRASES)
    if len(args) >= 3:
        phrase = pick_builtin_phrase(int(args[1]), int(args[2]))
    mode = args[3] if len(args) == 4 else None
    if mode == "--phrase-stdin":
        phrase = source.read(2048).decode("utf-8").strip() or phrase
    if mode == "--live-stdin":
        size = int.from_bytes(source.read(4), "little")
        if size > MAX_PHRASE_BYTES:
            raise SystemExit("Invalid phrase size.")
        phrase = source.read(size).decode("utf-8").strip() or phrase
        reference = source.read(MAX_LIVE_SAMPLE_BYTES + 1)
        if not valid_live_sample_size(len(reference)):
            raise SystemExit("Invalid live reference size.")
    else:
        reference = Path(args[0]).resolve(strict=True)
    with redirect_stdout(sys.stderr):
        pcm = generate(reference, phrase)
    output.write(pcm)


def main(args: list[str]) -> None:
    """Dispatch setup checks, orbital requests, and one-shot generation."""
    local_ffmpeg = RUNTIME / "ffmpeg"
    if (local_ffmpeg / "ffmpeg.exe").is_file():
        os.environ["PATH"] = str(local_ffmpeg) + os.pathsep + os.environ.get("PATH", "")

    if len(args) == 2 and args[0] == "--session":
        serve(args[1], sys.stdin.buffer, sys.stdout.buffer)
    elif args == ["--prepare-whisper"]:
        import whisper

        whisper.load_model("base", device="cpu", download_root=str(RUNTIME / "whisper-models"))
    elif args == ["--check"]:
        check_runtime()
    elif len(args) == 2 and args[0] == "--self-test":
        run_self_test(args[1])
    else:
        run_one_shot(args, sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    main(sys.argv[1:])
