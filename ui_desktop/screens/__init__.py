"""Stage 10–12 desktop screens (live sections; no placeholders remain).

Each builder returns a fresh ``QWidget`` for one registered section; the
shell caches one instance per section so repeated navigation can never
create duplicates. Screens consume the shared engine ONLY through
``ui_desktop.backend.DesktopBackend`` (or ``ConfigService`` /
``services.doctor`` for config-only pages) — they never build transports,
never run subprocesses, and never import the TUI.

Stage 12 flips the last future rows live: monitoring, forensics,
mirroring and demo data (``build_placeholder`` stays available for any
future-stage row the registry may carry again).
"""

from .dashboard import build_dashboard
from .demo import DemoPage
from .devices import DeviceWorkspacePage
from .doctor import build_doctor
from .forensics import ForensicsPage
from .help import build_help_section
from .mirroring import MirroringPage
from .monitoring import MonitoringPage
from .placeholder import build_placeholder
from .reports import ReportsPage
from .scan import ScanWorkspacePage

__all__ = [
    "build_dashboard",
    "build_doctor",
    "build_help_section",
    "build_placeholder",
    "DemoPage",
    "DeviceWorkspacePage",
    "ForensicsPage",
    "MirroringPage",
    "MonitoringPage",
    "ScanWorkspacePage",
    "ReportsPage",
]
