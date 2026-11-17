# Redmint Voice Setup

If you hear your crew calling from the next room, check who’s still on the radio.

Voice Setup adds optional voice imitation to Redmint for **Lethal Company**. Only the host installs it. Everyone else just needs the Redmint mod.

<!-- repository-only:start -->
![And here's the yapper](docs/redmint-yapper.gif)

<!-- repository-only:end -->

## Install

You’ll need Windows, an NVIDIA GPU with CUDA support, internet access during setup, and about **18 GiB** free on the drive that holds your r2modman profile.

1. Download the ZIP under **Assets** and extract it. [Latest release](https://github.com/WhoTookRedmint/redmint-voice-setup/releases/latest)
2. Close the game and run `Install-RedmintVoice.cmd`.
3. Select the root folder of the r2modman profile you use to host with Redmint installed, for example `LethalCompany\profiles\Redmint`. The selected folder should contain `BepInEx` directly inside it. When asked whether to use in-game voice chat, choose **Yes** for lobby voices or **No** to select a 1–15 second WAV you have permission to use.
4. Wait for the setup confirmation, then launch the same profile with **Start modded**.

The installer downloads Python, the voice tools and their models into the selected profile. After setup, launch Lethal Company as usual. Redmint starts the voice worker automatically while the ship is in orbit. It prepares up to ten lines in memory, then unloads the models as the ship starts landing. On the moon, Redmint plays whatever lines were ready before landing.

## In the lobby

With voice chat selected, each player can opt in through **Redmint voice imitation** in the pause menu. The switch starts off in each lobby. After opting in, talk normally for about five seconds while the ship is in orbit, then give the host time to prepare the first line. Turn the switch off at any time to revoke permission. The host keeps live samples and generated lines in memory and clears them on revocation, player departure or round end.

For the whole crew to hear the lines, set `ShareVoiceLures = true` under `[Voice]` in the host’s `BepInEx/config/redmint.cfg` and restart the game.

To give him your crew’s vocabulary, edit `BepInEx/config/Redmint/Voice/phrases.txt` in UTF‑8, with one line per phrase. The host picks up edits before the next generation. Leave the file empty to use the built-in English lines.

Redmint picks a ready line at random and avoids immediate repeats when another recording is available. Under `[Voice]` in the host’s `redmint.cfg`, `RefreshAfterPlays` controls when a line can be replaced (three plays by default). When the cache is full, `RefreshMinutes` sets the wait between replacements on orbit.

## Installer source

Keep `Install-RedmintVoice.cmd`, `Install-RedmintVoice.ps1` and `Generate-RedmintLure.py` together at the root, with the growl clips in `Growls/`. The CMD file launches setup, the PowerShell script installs and configures the runtime, and the Python worker generates the audio.

## Host hardware and performance

Tested on a **Ryzen 7 7800X3D** and **RTX 5070 Ti (16 GB)**. While generating on orbit, the system used about **4 GB more VRAM** and **5 GB more RAM** than on orbit without synthesis. Redmint had **six lines** ready by landing.

For a host aiming to generate **1–3 short lines while the crew waits in orbit**, start with a modern **6-core CPU**, **32 GB RAM**, and a desktop NVIDIA GPU around **RTX 3080 (10 GB)** or **RTX 4070 (12 GB)** class. The **RTX 5070 (12 GB)** is a faster option on paper. Generation times on these alternatives are still untested. How many lines finish depends on time in orbit, including model loading for the first line. [NVIDIA GPU specs](https://www.nvidia.com/en-us/geforce/graphics-cards/compare/)

Tried it on your rig? Share your CPU, GPU, RAM and how many lines were ready before landing. If setup or synthesis does something weird, tell us what happened and include the relevant log lines if you have them. [GitHub Issues](https://github.com/WhoTookRedmint/redmint-voice-setup/issues)
