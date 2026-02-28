"""
Entry point for the ByteCLI settings panel (``bytecli-settings``).
"""

from __future__ import annotations

import sys


def main() -> None:
    from bytecli.settings.app import ByteCLISettingsApp

    app = ByteCLISettingsApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
