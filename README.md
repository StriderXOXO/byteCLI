<div align="center">

# Byte CLI

**All bark, all byte.**

A fast, privacy-first voice input tool for Linux.<br>
Speak your code into existence. Zero cloud, all local.

[![Website](https://img.shields.io/badge/Website-byte--cli.com-FF8400?style=flat-square)](https://byte-cli.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square)](LICENSE)
[![Ubuntu 22.04+](https://img.shields.io/badge/Ubuntu-22.04%2B-E95420?style=flat-square&logo=ubuntu&logoColor=white)](https://ubuntu.com)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-94%20passed-B6FFCE?style=flat-square)](#)

[Website](https://byte-cli.com) · [Download .deb](https://github.com/StriderXOXO/byteCLI/releases) · [Report Bug](https://github.com/StriderXOXO/byteCLI/issues)

</div>

---

```
$ byte --status
● Online (Local Mode)
● Response: ~200ms
● Privacy: Sealed
● Model: small (465 MB)
```

<strong>0 bytes</strong> uploaded to the cloud. Ever.<br>
<strong>~200ms</strong> transcription response.<br>
<strong>1 hotkey</strong> — Ctrl+Alt+V, that's it.

---

## Quick Install

**Ubuntu / Debian (.deb):**

```bash
sudo apt install ./bytecli_1.0.0_amd64.deb
```

Download from [Releases](https://github.com/StriderXOXO/byteCLI/releases). The service starts automatically — look for the indicator pill at the bottom of your screen.

**Developer install:**

```bash
sudo apt install xclip xdotool portaudio19-dev python3-gi gir1.2-gtk-4.0
git clone https://github.com/StriderXOXO/byteCLI.git
cd byteCLI
pip install -e .
./scripts/install.sh
```

> Requires **Ubuntu 22.04+**, **X11** session (Wayland has limited support), **Python 3.10+**, and a microphone.

## Features

- **One hotkey to rule them all** — Ctrl+Alt+V. Hold to record, release to paste. Done.
- **Your voice stays yours** — Runs entirely on your machine. Zero telemetry, zero cloud, zero API keys.
- **Know what's happening** — A tiny pill at the bottom of your screen. Recording? You'll see it. Downloading model? Progress right there.
- **Fast enough to not think about it** — CUDA GPU support for ~200ms response. CPU works too.
- **你好, world** — English and Chinese out of the box.
- **Choose your tradeoff** — Tiny (75 MB, instant) → Small (465 MB, balanced) → Medium (1.5 GB, accurate).

## Why does this exist?

> I opened a project to build a health dashboard for my Maltese, Dolly. I closed it with a fully functional local voice-to-text engine.
>
> Why? Because typing breaks the flow. Byte restores it. No API keys, no monthly fees, just raw input.

## Architecture

Three processes, one D-Bus:

```
┌─────────────────────┐
│   bytecli-service    │  Background daemon: Whisper engine, audio,
│   (systemd user)     │  hotkey listener, recording state machine
└─────────┬───────────┘
          │ D-Bus (com.bytecli.ServiceInterface)
          │
    ┌─────┴─────┐
    │           │
┌───▼───┐  ┌───▼────────┐
│indicator│  │  settings   │  GTK 4 apps: floating pill indicator
│ (pill) │  │   (GUI)     │  and configuration panel
└────────┘  └─────────────┘
```

- **bytecli-service** — systemd user service that loads the Whisper model, listens for the global hotkey, records audio, transcribes, and pastes text via xdotool/xclip
- **bytecli-indicator** — floating pill-shaped GTK 4 window pinned to the bottom-center of the screen showing idle/recording state with an elapsed timer
- **bytecli-settings** — dark GTK 4 settings app for model selection, audio device, hotkey configuration, and service control

## Configuration

`~/.config/bytecli/config.json`:

```json
{
  "model": "small",
  "device": "gpu",
  "audio_input": "auto",
  "hotkey": { "keys": ["Ctrl", "Alt", "V"] },
  "language": "en",
  "auto_start": false,
  "history_max_entries": 50
}
```

### Model Catalogue

| Model  | Size     | Speed   | Accuracy |
|--------|----------|---------|----------|
| tiny   | ~75 MB   | Fastest | Basic    |
| small  | ~465 MB  | Good    | Good     |
| medium | ~1.5 GB  | Slower  | Best     |

Models are downloaded automatically on first use to `~/.local/share/bytecli/models/`.

## Troubleshooting

**Service won't start**
```bash
systemctl --user status bytecli
journalctl --user -u bytecli -n 50
```

**Indicator not visible**
- Ensure the service is running: `systemctl --user is-active bytecli`
- Check that you are on X11 (Wayland support is limited)

**No transcription / silent paste**
- Verify your microphone is working: `arecord -d 3 test.wav && aplay test.wav`
- Check audio device in ByteCLI Settings

**GPU not detected**
- Ensure NVIDIA drivers and CUDA toolkit are installed
- Verify: `python3 -c "import torch; print(torch.cuda.is_available())"`

**Model download seems stuck**
- First-run downloads can take several minutes depending on your connection
- The indicator pill shows download progress; check logs at `~/.local/share/bytecli/logs/bytecli.log`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development guide.

## License

[MIT](LICENSE)

---

<div align="center">

**[byte-cli.com](https://byte-cli.com)**

Made with ❤️ and 🦴 for Dolly

</div>
