#!/usr/bin/env python3
"""Download the images in demo_assets/parts/sources.json and save them in one format.

Every image becomes an 800x800 JPEG on a white background, named <task id>.jpg.
Needs Pillow (pip install -r data/requirements.txt).

    python3 data/scripts/fetch_images.py
"""
import io
import json
import urllib.request
from pathlib import Path

from PIL import Image

PARTS_DIR = Path(__file__).resolve().parents[1] / "demo_assets" / "parts"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
SIZE = 800
MARGIN = 40


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def normalize(data):
    image = Image.open(io.BytesIO(data)).convert("RGBA")
    image.thumbnail((SIZE - 2 * MARGIN, SIZE - 2 * MARGIN), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
    canvas.alpha_composite(image, ((SIZE - image.width) // 2, (SIZE - image.height) // 2))
    return canvas.convert("RGB")


def main():
    sources = json.loads((PARTS_DIR / "sources.json").read_text())
    for task_id, source in sources.items():
        path = PARTS_DIR / f"{task_id}.jpg"
        normalize(download(source["image"])).save(path, "JPEG", quality=88, optimize=True)
        print(f"{path.name}: {source['subject']}")


if __name__ == "__main__":
    main()
