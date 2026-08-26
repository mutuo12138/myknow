"""Generate the Windows ICO from the repository's current brand source image."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = ROOT / "assets" / "icon-redesign-20260825" / "myknow-icon-viewfinder-v1.png"
DEFAULT_OUTPUT = ROOT / "assets" / "myknow.ico"
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"Icon source does not exist: {args.source}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(args.source) as image:
        rgba = image.convert("RGBA")
        rgba.save(args.output, format="ICO", sizes=ICO_SIZES)

    print(f"Generated {args.output} from {args.source}")
    print(f"Sizes: {', '.join(f'{width}x{height}' for width, height in ICO_SIZES)}")


if __name__ == "__main__":
    main()
