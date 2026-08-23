from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"


def make_image(path: Path, index: int, *, jpeg: bool = False) -> None:
    colors = ["#ef8f9f", "#55b89c", "#5b8ee6", "#e6a25b", "#9b78d0"]
    image = Image.new("RGB", (320, 220), colors[index - 1])
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 24, 296, 196), outline="white", width=5)
    draw.line((24, 196, 296, 24), fill="#17231f", width=4)
    draw.text((38, 42), f"Muse Vault {index}", fill="#17231f")
    image.save(path, format="JPEG" if jpeg else "PNG", quality=82)


def make_pdf(path: Path, index: int) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    document = canvas.Canvas(str(path), pagesize=A4)
    document.setFont("STSong-Light", 18)
    document.drawString(72, 760, f"Muse Vault 验收文档 {index}")
    document.setFont("STSong-Light", 11)
    document.drawString(72, 720, "用于验证文档落盘、内容哈希与失败恢复。")
    document.save()


def build() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []

    for index in range(1, 6):
        path = FIXTURES / f"image-{index:02d}.png"
        make_image(path, index)
        items.append({
            "id": f"image-{index:02d}",
            "material_type": "image",
            "file": path.name,
            "expected": "ready",
            "title": f"本地验收图片 {index}",
        })

    for index in range(1, 6):
        preview = FIXTURES / f"page-{index:02d}-preview.jpg"
        html = FIXTURES / f"page-{index:02d}.html"
        make_image(preview, index, jpeg=True)
        html.write_text(
            "<!doctype html><html lang='zh-CN'><head>"
            f"<title>Muse Vault 验收网页 {index}</title></head><body>"
            f"<h1>验收网页 {index}</h1><p>蓝色头发的本地测试正文 {index}，用于验证截图、快照和中文检索。</p>"
            "</body></html>",
            encoding="utf-8",
        )
        items.append({
            "id": f"page-{index:02d}",
            "material_type": "page",
            "file": html.name,
            "preview": preview.name,
            "expected": "ready",
            "title": f"本地验收网页 {index}",
        })

    for index in range(1, 6):
        path = FIXTURES / f"document-{index:02d}.pdf"
        make_pdf(path, index)
        items.append({
            "id": f"document-{index:02d}",
            "material_type": "document",
            "file": path.name,
            "expected": "ready",
            "title": f"本地验收文档 {index}",
        })

    for index in range(1, 6):
        poster = FIXTURES / f"video-{index:02d}-poster.jpg"
        make_image(poster, index, jpeg=True)
        items.append({
            "id": f"video-{index:02d}",
            "material_type": "video",
            "file": None,
            "preview": poster.name,
            "expected": "reference_only" if index < 5 else "expected_failure",
            "title": f"本地验收视频引用 {index}",
            "failure_reason": "故意使用不可达媒体地址" if index == 5 else None,
        })

    manifest = {
        "version": 1,
        "purpose": "Muse Vault P0-A persistent acceptance fixtures",
        "counts": {"image": 5, "page": 5, "document": 5, "video": 5},
        "failure_cases": [
            {"id": "integrity-forced-file-commit-failure", "kind": "capture", "expected": "failed"},
            {"id": "worker-download-unreachable", "kind": "download", "expected": "dead-after-retries"},
        ],
        "items": items,
    }
    (ROOT / "fixtures-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    build()
