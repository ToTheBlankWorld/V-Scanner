"""Application icon generation (Stage 14).

The repository ships no third-party binary blobs: the application icon is
generated here with PySide6's QPainter against the Stage 10/13 dark theme
palette (surface ``#1B222E`` with the control accent ramp ending in
``#5B8AF5``), then assembled into a single-file Windows icon by hand
(ICONDIR + ICONDIRENTRY + PNG payloads — the container Windows Vista and
later decode natively). The committed artifact is
``packaging_windows/assets/vscanner.ico``; this module exists so the asset
is reproducible, not vendored.

Regenerate with:

    python -m packaging_windows.icon

The generator validates its own output: the ICO directory is parsed back
and the artifact is loaded through QImage before it is accepted.
"""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

__all__ = ["ICON_SIZES", "generate_icon", "assemble_ico"]

ICON_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

# Stage 10/13 dark theme tokens (colors must not create new literals in
# ui_desktop; these are packaging-local theme-mirroring constants).
_BG = QColor("#1B222E")
_BG_EDGE = QColor("#161C26")
_ACCENT = QColor("#5B8AF5")
_ACCENT_DEEP = QColor("#3E6ED8")


def _render_size(size: int) -> QImage:
    """Render one square icon frame at *size* pixels."""
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    inset = max(1, size // 16)
    rect = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    radius = rect.width() * 0.22

    # Rounded card: dark surface with a slightly deeper bottom edge.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_BG_EDGE)
    painter.drawRoundedRect(rect.translated(0, max(1, size / 64)), radius, radius)
    painter.setBrush(_BG)
    painter.drawRoundedRect(rect, radius, radius)

    # The brand mark: a wide scan-style "V" cut with the accent ramp.
    stroke = rect.width() * 0.16
    path = QPainterPath()
    left = QPointF(rect.left() + rect.width() * 0.26,
                   rect.top() + rect.height() * 0.32)
    bottom = QPointF(rect.center().x(), rect.bottom() - rect.height() * 0.28)
    right = QPointF(rect.right() - rect.width() * 0.26,
                    rect.top() + rect.height() * 0.32)
    path.moveTo(left)
    path.lineTo(bottom)
    path.lineTo(right)
    pen = QPen(_ACCENT_DEEP, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path.translated(0, max(1, size / 48)))
    pen.setColor(_ACCENT)
    painter.setPen(pen)
    painter.drawPath(path)

    painter.end()
    return image


def _png_bytes(image: QImage) -> bytes:
    """PNG-encode *image* (payload format for the ICO entries).

    PySide6 stubs mismatch here; both calls are verified at runtime.
    """
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")  # type: ignore[call-overload]
    payload = bytes(buffer.data())  # type: ignore[call-overload]
    return payload


def assemble_ico(payloads: "list[tuple[int, bytes]]") -> bytes:
    """Assemble ICO container bytes from (size, PNG) payloads.

    Entries are ordered ascending by size; ICONDIRENTRY width/height bytes
    use the 0 sentinel for the 256px entry.
    """
    payloads = sorted(payloads, key=lambda item: item[0])
    count = len(payloads)
    header = struct.pack("<HHH", 0, 1, count)
    entries: list[bytes] = []
    offset = 6 + count * 16
    for size, png in payloads:
        width = 0 if size >= 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII", width, width, 0, 0, 1, 32, len(png), offset
            )
        )
        offset += len(png)
    body = b"".join(png for _size, png in payloads)
    return header + b"".join(entries) + body


def generate_icon(out_path: Path) -> list[int]:
    """Render, assemble, write, and validate the application icon."""
    payloads: list[tuple[int, bytes]] = [
        (size, _png_bytes(_render_size(size))) for size in ICON_SIZES
    ]
    data = assemble_ico(payloads)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)

    # Validate by parse + Qt load-back (structural parse mirrored from
    # packaging_windows.validation to keep this module self-contained).
    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count != len(ICON_SIZES):
        raise ValueError("assembled ICO has an invalid directory header")
    image = QImage(str(out_path))
    if image.isNull():
        raise ValueError("Qt failed to decode the generated icon")
    return [size for size, _png in payloads]


def main() -> int:  # pragma: no cover - manual regeneration CLI
    import argparse

    parser = argparse.ArgumentParser(
        prog="packaging_windows.icon",
        description="regenerate packaging_windows/assets/vscanner.ico")
    default = Path(__file__).resolve().parent / "assets" / "vscanner.ico"
    parser.add_argument("--out", type=Path, default=default)
    args = parser.parse_args()
    sizes = generate_icon(args.out)
    print(f"wrote {args.out} with {len(sizes)} entries: {sizes}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
