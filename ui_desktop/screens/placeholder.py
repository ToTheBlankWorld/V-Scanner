"""Honest future-stage placeholder screen (Stage 09 mission §3)."""

from __future__ import annotations

from ..sections import DesktopSection
from ..widgets import PlaceholderState

__all__ = ["build_placeholder"]


def build_placeholder(section: DesktopSection) -> PlaceholderState:
    return PlaceholderState(section)
