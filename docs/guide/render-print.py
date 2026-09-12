"""Refresh print review images and text evidence from the current guide PDF.

Run from repository root: uv run --project pdf-shrink python docs/guide/render-print.py
"""
import hashlib
import json
from pathlib import Path

import pymupdf


def main():
    folder = Path(__file__).resolve().parent / "validation"
    source = folder / "guide.a4.pdf"
    rows = []
    with pymupdf.open(source) as document:
        for index, page in enumerate(document):
            inside = all(page.rect.contains(pymupdf.Rect(word[:4]))
                         for word in page.get_text("words"))
            if not inside:
                raise ValueError(f"Guide text outside page {index + 1}")
            page.get_pixmap(dpi=100).save(str(folder / f"guide.a4.page-{index + 1}.png"))
            rows.append({"page": index + 1, "width": round(page.rect.width, 1),
                         "height": round(page.rect.height, 1), "text_bounds_inside_page": inside,
                         "text": page.get_text()})
    result = {"pdf_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "page_count": len(rows), "pages": rows}
    source.with_suffix(".pages.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Refreshed {len(rows)} pages; text bounds passed. Visual review is still required.")


if __name__ == "__main__":
    main()
