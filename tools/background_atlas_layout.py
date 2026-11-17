"""Compile imagegen art into the measured original model's repeating UV slots.

This is texture-atlas export, not a replacement for authored regional artwork.
The native foreground repeats original grass; the four distant panels sample
the atlas strips in the order C, B, A, C (horizontally reversed by the mesh).
"""
from __future__ import annotations

DISTANT_TOPS = (1, 287, 573)
DISTANT_WIDTH, DISTANT_HEIGHT = 1022, 285
GRASS_BOX = (0, 0, 576, 144)


def continuous_distant(image):
    from PIL import Image, ImageOps
    if image.size != (1024, 1024):
        raise ValueError('original 1024-square distant atlas required')
    output = image.copy()
    # The mesh has three cyclic slots, not three independent scenic paintings.
    # Mirror one continuous master view to close the cycle, then share the
    # boundary pixel between adjacent slices. No model/UV changes are needed.
    master = image.crop((1, 1, 1023, 286)).resize((1532, 285), Image.Resampling.LANCZOS)
    panorama = Image.new('RGBA', (3064, 285))
    panorama.paste(master, (0, 0))
    panorama.paste(ImageOps.mirror(master), (1532, 0))
    for index, top in enumerate(DISTANT_TOPS):
        start = index * 1021
        panel = panorama.crop((start, 0, start + 1022, 285))
        output.paste(panel, (1, top))
        output.paste(panel.crop((0, 0, 1, 285)), (0, top))
        output.paste(panel.crop((1021, 0, 1022, 285)), (1023, top))
        output.paste(output.crop((0, top, 1024, top + 1)), (0, top - 1))
        output.paste(output.crop((0, top + 284, 1024, top + 285)), (0, top + 285))
    # The separate sky mesh repeats this strip four times horizontally.
    half = image.crop((0, 859, 512, 1024))
    output.paste(half, (0, 859))
    output.paste(ImageOps.mirror(half), (512, 859))
    return output


def preserve_grass_pixels(image, reference):
    output = image.copy()
    output.paste(reference.crop(GRASS_BOX), GRASS_BOX[:2])
    return output


def preserve_grass_bc3(encoded: bytes, original: bytes) -> bytes:
    if len(encoded) != 1048576 or len(original) != len(encoded):
        raise ValueError('original 1024-square BC3 payload required')
    output = bytearray(encoded)
    # Unity texture rows are bottom-up. Copy complete original 4x4 BC3 blocks,
    # including padding around both grass UV rectangles, without recompression.
    for row in range((1024 - GRASS_BOX[3]) // 4, 256):
        start = row * 256 * 16
        end = start + GRASS_BOX[2] // 4 * 16
        output[start:end] = original[start:end]
    return bytes(output)


def join_error(image) -> list[list[float]]:
    from PIL import ImageChops, ImageStat
    rows = [image.crop((1, top, 1023, top + 285)) for top in DISTANT_TOPS]
    return [ImageStat.Stat(ImageChops.difference(
        rows[i].crop((1021, 0, 1022, 285)),
        rows[(i + 1) % 3].crop((0, 0, 1, 285)))).mean for i in range(3)]
