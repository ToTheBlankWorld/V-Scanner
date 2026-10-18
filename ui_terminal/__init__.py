"""V-Scanner 3.0 — ui_terminal (interface layer, Stages 05-08).

Stage 05 adds the Textual application shell: the entry point
(``app.main`` / ``python -m ui_terminal`` / ``vscanner-tui``), the design
token layer (``theme``), the navigation registry (``sections``) and the
first screens (dashboard, doctor, settings, help, future-stage
placeholders). The Stage 04 framework-free adapter stub
(``jobs_bridge_async.py``) remains and is adopted by later stages.

This package must never be imported by ``vscanner`` or core contracts.
"""

from ui_terminal import sections  # noqa: F401  (registry is the nav contract)

__all__ = ["sections"]
