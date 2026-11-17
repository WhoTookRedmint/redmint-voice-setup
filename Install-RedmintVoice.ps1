[CmdletBinding()]
param([string]$ProfilePath, [string]$ReferenceWav, [switch]$LiveChat, [switch]$ConfigureOnly)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms

function Invoke-Checked {
    param([string]$Executable, [string[]]$CommandArgs)
    & $Executable @CommandArgs
    if ($LASTEXITCODE -ne 0) { throw "$Executable exited with code $LASTEXITCODE." }
}

function Get-Archive {
    param([string]$Url, [string]$Archive, [string]$Destination, [switch]$StripRoot)
    if (!(Test-Path -LiteralPath $Archive)) {
        Invoke-WebRequest -UseBasicParsing $Url -OutFile "$Archive.part"
        Move-Item -LiteralPath "$Archive.part" -Destination $Archive
    }
    New-Item -Path $Destination -ItemType Directory -Force | Out-Null
    $tarArgs = @('-xf', $Archive, '-C', $Destination)
    if ($StripRoot) { $tarArgs += '--strip-components=1' }
    Invoke-Checked 'tar.exe' $tarArgs
}

if (!$ProfilePath) {
    $picker = New-Object System.Windows.Forms.FolderBrowserDialog
    $picker.Description = 'Select a Lethal Company r2modman profile containing BepInEx'
    $picker.SelectedPath = Join-Path $env:APPDATA 'r2modmanPlus-local\LethalCompany\profiles'
    if ($picker.ShowDialog() -ne 'OK') { return }
    $ProfilePath = $picker.SelectedPath
}
$profileRoot = (Resolve-Path -LiteralPath $ProfilePath).Path
if (!(Test-Path -LiteralPath (Join-Path $profileRoot 'BepInEx') -PathType Container)) {
    throw 'Select an installed r2modman profile, not the profiles parent folder.'
}
if (Get-Process -Name 'Lethal Company' -ErrorAction SilentlyContinue) {
    throw 'Close Lethal Company before configuring the profile.'
}
if (!$ReferenceWav -and !$LiveChat) {
    $choice = [Windows.Forms.MessageBox]::Show(
        'Use in-game voice with per-player consent? Choose No to select a reference WAV instead.',
        'Redmint voice source', [Windows.Forms.MessageBoxButtons]::YesNoCancel)
    if ($choice -eq 'Cancel') { return }
    $LiveChat = $choice -eq 'Yes'
}
if (!$ReferenceWav -and !$LiveChat) {
    $picker = New-Object System.Windows.Forms.OpenFileDialog
    $picker.Title = 'Select your own reference WAV (1–15 seconds)'
    $picker.Filter = 'WAV audio (*.wav)|*.wav'
    if ($picker.ShowDialog() -ne 'OK') { return }
    $ReferenceWav = $picker.FileName
}
$reference = if ($ReferenceWav) { (Resolve-Path -LiteralPath $ReferenceWav).Path } else { '' }
$configRoot = Join-Path $profileRoot 'BepInEx\config'
$settings = Join-Path $configRoot 'Redmint\Voice'
$legacySettings = Join-Path $configRoot 'Redmint\VoicePlaytest'
$runtime = Join-Path $configRoot 'Redmint\VoiceRuntime'
$downloads = Join-Path $runtime 'downloads'
$python = Join-Path $runtime '.venv\Scripts\python.exe'
$worker = Join-Path $runtime 'Generate-RedmintLure.py'
$env:REDMINT_VOICE_RUNTIME = $runtime
$assetSource = Join-Path $PSScriptRoot 'Growls'
if (!(Test-Path -LiteralPath $assetSource)) { $assetSource = Join-Path (Split-Path -Parent $PSScriptRoot) 'Audio\Voice' }
New-Item -Path $settings, $runtime, $downloads -ItemType Directory -Force | Out-Null
foreach ($name in @('phrases.txt','lure.wav')) {
    $source = Join-Path $legacySettings $name
    $target = Join-Path $settings $name
    if ((Test-Path -LiteralPath $source -PathType Leaf) -and !(Test-Path -LiteralPath $target)) {
        Copy-Item -LiteralPath $source -Destination $target
    }
}

if (!$ConfigureOnly -and !(Test-Path -LiteralPath (Join-Path $runtime '.ready-v1'))) {
    $free = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($runtime)).AvailableFreeSpace
    if (!(Test-Path -LiteralPath $python) -and $free -lt 18GB) {
        throw 'Free at least 18 GiB for the download and local voice environment.'
    }
    if (!(Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue)) {
        throw 'This installer targets Windows hosts with an NVIDIA CUDA GPU. Redmint can still play a ready lure.wav.'
    }
    $uvHome = Join-Path $runtime 'bootstrap'
    Get-Archive 'https://github.com/astral-sh/uv/releases/download/0.11.16/uv-x86_64-pc-windows-msvc.zip' (Join-Path $downloads 'uv.zip') $uvHome
    $uv = (Get-ChildItem -LiteralPath $uvHome -Filter 'uv.exe' -Recurse -File | Select-Object -First 1).FullName
    Get-Archive 'https://codeload.github.com/QwenAudio/CosyVoice/tar.gz/074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc' (Join-Path $downloads 'cosyvoice.tar.gz') (Join-Path $runtime 'source') -StripRoot
    Get-Archive 'https://codeload.github.com/shivammehta25/Matcha-TTS/tar.gz/dd9105b34bf2be2230f4aa1e4769fb586a3c824e' (Join-Path $downloads 'matcha.tar.gz') (Join-Path $runtime 'source\third_party\Matcha-TTS') -StripRoot
    Get-Archive 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' (Join-Path $downloads 'ffmpeg.zip') (Join-Path $downloads 'ffmpeg') -StripRoot
    $ffmpegHome = Join-Path $runtime 'ffmpeg'
    New-Item -Path $ffmpegHome -ItemType Directory -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $downloads 'ffmpeg\bin\ffmpeg.exe') -Destination $ffmpegHome -Force
    $env:UV_CACHE_DIR = Join-Path $runtime 'uv-cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtime 'python'
    $env:UV_NO_CACHE = '1'
    $env:HF_HUB_DISABLE_TELEMETRY = '1'
    $env:HF_HUB_DISABLE_IMPLICIT_TOKEN = '1'
    $env:HF_XET_CACHE = Join-Path $runtime 'xet-cache'
    if (!(Test-Path -LiteralPath $python)) {
        Invoke-Checked $uv @('venv','--python','3.10',(Join-Path $runtime '.venv'))
    }
    Invoke-Checked $uv @('pip','install','--python',$python,'--index-url','https://download.pytorch.org/whl/cu128','torch==2.7.1','torchaudio==2.7.1')
    $deps = @('conformer==0.3.2','diffusers==0.29.0','HyperPyYAML==1.2.3','inflect==7.3.1',
        'librosa==0.10.2','modelscope==1.20.0','numpy==1.26.4','onnxruntime==1.18.0',
        'openai-whisper==20250625','soundfile==0.12.1','transformers==4.51.3','x-transformers==2.11.24',
        'wetext==0.0.4','omegaconf==2.3.0','lightning==2.2.4','scipy<1.16','setuptools<81','datasets<3',
        'pyarrow','rich','hydra-core==1.3.2','matplotlib==3.7.5','rootutils','einops','tensorboard',
        'pytorch-lightning==2.2.4','gdown==5.1.0','wget==3.2','pyworld==0.3.5')
    Invoke-Checked $uv (@('pip','install','--python',$python) + $deps)
    $model = Join-Path $runtime 'models\Fun-CosyVoice3-0.5B'
    Invoke-Checked $uv @('tool','run','--from','huggingface-hub','hf','download','FunAudioLLM/Fun-CosyVoice3-0.5B-2512',
        '--revision','29e01c4e8d000f4bcd70751be16fa94bf3d85a18','--local-dir',$model,
        '--exclude','llm.rl.pt','--exclude','flow.decoder.estimator.fp32.onnx','--exclude','speech_tokenizer_v3.batch.onnx','--max-workers','3')
    Invoke-Checked $python @((Join-Path $PSScriptRoot 'Generate-RedmintLure.py'),'--prepare-whisper')
    Set-Content -LiteralPath (Join-Path $runtime '.ready-v1') -Value 'runtime v1' -Encoding ascii
}

if (!(Test-Path -LiteralPath $python)) { throw 'The local voice runtime is missing.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Generate-RedmintLure.py') -Destination $worker -Force
$growls = Join-Path $runtime 'Growls'
New-Item -Path $growls -ItemType Directory -Force | Out-Null
Get-ChildItem -LiteralPath $assetSource -Filter 'Growl*.pcm' -File | Copy-Item -Destination $growls -Force
Invoke-Checked $python @($worker,'--check')
# Verify the full generation path. PCM stays in the test process and is discarded.
if ($reference) {
    Invoke-Checked $python @($worker,'--self-test',$reference)
}

$config = Join-Path $configRoot 'redmint.cfg'
$legacyConfig = Join-Path $configRoot 'redmint.playtest.cfg'
$hasConfig = Test-Path -LiteralPath $config -PathType Leaf
$before = if ($hasConfig) {
    [IO.File]::ReadAllText($config)
} elseif (Test-Path -LiteralPath $legacyConfig -PathType Leaf) {
    [IO.File]::ReadAllText($legacyConfig)
} else { '' }
$original = $before
$sectionBody = '[^\S\r\n]*\r?\n(?<body>.*?)(?=^\[|\z)'
$legacy = [regex]::Match($before, '(?ms)^\[VoicePlaytest\]' + $sectionBody)
$legacyBody = ''
if ($legacy.Success) {
    $legacyBody = [regex]::Replace($legacy.Groups['body'].Value, '(?m)^(\s*)ShareTestClip(?=\s*=)', '${1}ShareVoiceLures')
    $before = $before.Remove($legacy.Index, $legacy.Length)
}
$section = [regex]::Match($before, '(?ms)^\[Voice\]' + $sectionBody)
$body = $legacyBody.TrimEnd() + "`r`n" + $section.Groups['body'].Value
$values = [ordered]@{ VoiceRuntimePath=$runtime; ShowSetupPrompt='false'; LiveChatSynthesis=([bool]$LiveChat).ToString().ToLowerInvariant() }
if ($reference) { $values['ReferenceWav'] = $reference }
foreach ($key in $values.Keys) {
    $line = "$key = $($values[$key])"
    $pattern = '(?m)^'+[regex]::Escape($key)+'[^\S\r\n]*=[^\r\n]*'
    if ([regex]::IsMatch($body,$pattern)) {
        $body=[regex]::Replace($body,$pattern,[Text.RegularExpressions.MatchEvaluator]{param($match) $line})
    } else {
        $body = $body.TrimEnd() + "`r`n" + $line
    }
}
$replacement = "[Voice]`r`n"+$body.Trim()+"`r`n`r`n"
$updated = if ($section.Success) {
    $before.Substring(0,$section.Index)+$replacement+$before.Substring($section.Index+$section.Length)
} else { $before.TrimEnd()+"`r`n`r`n"+$replacement }
if (!$hasConfig -or $updated -ne $original) {
    $pending = "$config.$([guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($pending,$updated)
        if (Test-Path -LiteralPath $config) {
            $backup = "$config.$([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff')).bak"
            [IO.File]::Replace($pending,$config,$backup)
        } else {
            [IO.File]::Move($pending,$config)
        }
    } finally {
        if (Test-Path -LiteralPath $pending) { Remove-Item -LiteralPath $pending }
    }
}
$phrases = Join-Path $settings 'phrases.txt'
if (!(Test-Path -LiteralPath $phrases)) {
    Set-Content -LiteralPath $phrases -Encoding UTF8 -Value '# One phrase per line. Blank files use the built-in phrases.'
}
[Windows.Forms.MessageBox]::Show("Voice setup passed. Start the selected profile in r2modman.`r`nEdit phrases in:`r`n$phrases",'Redmint voice setup') | Out-Null
