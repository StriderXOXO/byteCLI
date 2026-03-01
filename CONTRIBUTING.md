# Contributing to ByteCLI

Thanks for your interest in contributing!

## Development Setup

1. Install system dependencies:

```bash
sudo apt install xclip xdotool portaudio19-dev python3-gi gir1.2-gtk-4.0
```

2. Clone and install in editable mode:

```bash
git clone https://github.com/StriderXOXO/byteCLI.git
cd byteCLI
pip install -e .
```

3. Install the systemd service and desktop entries:

```bash
./scripts/install.sh
```

## Running Tests

```bash
python3 -m pytest tests/ -v
```

All 94 tests should pass. Tests use mocks for GTK, D-Bus, and Whisper dependencies, so no GPU or audio hardware is needed.

## Code Style

- Follow the existing code style (no strict linter enforced)
- Use type hints where practical
- Keep docstrings for public APIs

## Project Structure

```
bytecli/
  service/     # Background daemon (Whisper, audio, hotkey, D-Bus)
  indicator/   # Floating pill widget (GTK 4)
  settings/    # Settings GUI (GTK 4)
  shared/      # CSS loader, D-Bus client, logging
  i18n/        # Translations (en.json, zh.json)
  data/        # CSS stylesheet, D-Bus XML
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b my-feature`)
3. Make your changes and add tests if applicable
4. Run `python3 -m pytest tests/ -v` to verify all tests pass
5. Commit with a clear message
6. Open a Pull Request

## Reporting Bugs

Open an issue with:
- Ubuntu version and desktop environment
- Steps to reproduce
- Relevant logs from `journalctl --user -u bytecli -n 50`
