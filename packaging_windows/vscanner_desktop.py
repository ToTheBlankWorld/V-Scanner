"""Thin launcher for the packaged V-Scanner desktop application (Stage 14).

Nuitka compiles this file as the main module of ``V-Scanner.exe``. It has
exactly one job — delegate to the real application entry point — and it
must stay that way (STAGE_14 mission §4: no second entry point may bypass
``ui_desktop.app`` initialization, cleanup, or safety checks; tests lock
the allowed import set and the delegation call).

Command-line options are handled entirely inside the real entry point
(``--version`` / ``--smoke``); nothing is parsed or redirected here.
"""

import sys

from ui_desktop.app import main

if __name__ == "__main__":
    sys.exit(main())
