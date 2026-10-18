"""Stage 09 desktop screens (live sections + honest placeholders).

Each builder returns a fresh ``QWidget`` for one registered section; the
shell caches one instance per section so repeated navigation can never
create duplicates. Screens consume the shared engine through services
(``ConfigService``, ``services.doctor``) only — they never touch devices,
subprocesses, or the TUI.

Placeholder sections (``sections.kind == "future"``) render
``PlaceholderState`` — truthful future-stage labels, no faked content.
"""

from .dashboard import build_dashboard
from .doctor import build_doctor
from .help import build_help_section
from .placeholder import build_placeholder

__all__ = [
    "build_dashboard",
    "build_doctor",
    "build_help_section",
    "build_placeholder",
]
