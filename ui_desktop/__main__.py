"""``python -m ui_desktop`` — desktop application launch (Stage 09).

A missing PySide6 produces a single honest instruction line instead of a
traceback (the engine-only environment is a supported configuration; the
desktop extra is opt-in).
"""

from __future__ import annotations

import sys


def _launch() -> int:
    try:
        from ui_desktop.app import main
    except ImportError as exc:
        sys.exit(
            "V-Scanner desktop requires PySide6. Install it with the "
            f"desktop extra: pip install -e '.[desktop]' (import error: {exc})"
        )
    return main()


if __name__ == "__main__":
    raise SystemExit(_launch())
