"""Build the rounded app icons from the original square Stella logo.

Run on macOS with Pillow installed: python3 scripts/generate-mac-icon.py
The generated PNG is also used for the Dock icon at runtime.
"""

from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/renderer/src/assets/logo.png"
RESOURCES = ROOT / "resources"
ICON_SIZE = 1024
CORNER_RADIUS = 220
SCALE = 4


def main() -> None:
    logo = Image.open(SOURCE).convert("RGBA")
    if logo.size != (ICON_SIZE, ICON_SIZE):
        raise ValueError(f"Expected a {ICON_SIZE}px square logo, got {logo.size}")

    # Supersample the mask so the transparent corners stay smooth in the Dock.
    mask = Image.new("L", (ICON_SIZE * SCALE, ICON_SIZE * SCALE), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(
        (0, 0, ICON_SIZE * SCALE - 1, ICON_SIZE * SCALE - 1),
        radius=CORNER_RADIUS * SCALE,
        fill=255,
    )
    logo.putalpha(mask.resize(logo.size, Image.Resampling.LANCZOS))
    png_path = RESOURCES / "icon.png"
    logo.save(png_path)

    with tempfile.TemporaryDirectory() as temp:
        iconset = Path(temp) / "Stella.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            logo.resize((size, size), Image.Resampling.LANCZOS).save(
                iconset / f"icon_{size}x{size}.png"
            )
            logo.resize((size * 2, size * 2), Image.Resampling.LANCZOS).save(
                iconset / f"icon_{size}x{size}@2x.png"
            )
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(RESOURCES / "icon.icns")],
            check=True,
        )


if __name__ == "__main__":
    main()
