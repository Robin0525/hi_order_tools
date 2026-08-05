from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "shopkeeper-logo.png"
TARGET = ROOT / "assets" / "hipersonalization.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_bytes(image: QImage, size: int) -> bytes:
    scaled = image.scaled(
        QSize(size, size),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not scaled.save(buffer, "PNG"):
        raise RuntimeError(f"无法生成 {size}×{size} PNG 图层。")
    return bytes(data)


def main() -> None:
    source = QImage(str(SOURCE))
    if source.isNull():
        raise RuntimeError(f"无法读取图标源文件：{SOURCE}")
    layers = [(size, png_bytes(source, size)) for size in SIZES]
    header_size = 6 + 16 * len(layers)
    offset = header_size
    entries: list[bytes] = []
    payloads: list[bytes] = []
    for size, payload in layers:
        dimension = 0 if size == 256 else size
        entries.append(
            struct.pack(
                "<BBBBHHII",
                dimension,
                dimension,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        payloads.append(payload)
        offset += len(payload)
    TARGET.write_bytes(
        struct.pack("<HHH", 0, 1, len(layers)) + b"".join(entries) + b"".join(payloads)
    )
    print(f"Created {TARGET} with {len(layers)} sizes.")


if __name__ == "__main__":
    main()
