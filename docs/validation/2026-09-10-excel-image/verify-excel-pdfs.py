"""Compare the synthetic Excel-exported PDFs with the existing PDF environment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parent / "excel-native")
    parser.add_argument("--cases", nargs="+", default=["jpeg", "png", "small"])
    args = parser.parse_args()
    directory = args.directory.resolve()
    results = []
    for name in args.cases:
        with pymupdf.open(directory / f"{name}-source.pdf") as source, pymupdf.open(
            directory / f"{name}-output.pdf"
        ) as output:
            assert len(source) == len(output) == 1
            before, after = source[0], output[0]
            assert before.rect == after.rect
            assert before.get_text("words") == after.get_text("words")
            bounds = [pymupdf.Rect(i["bbox"]) for i in before.get_image_info()]
            assert bounds == [pymupdf.Rect(i["bbox"]) for i in after.get_image_info()]
            original = before.get_pixmap(dpi=144, alpha=False)
            resized = after.get_pixmap(dpi=144, alpha=False)
            assert (original.width, original.height, original.n) == (resized.width, resized.height, resized.n)
            samples1, samples2 = original.samples, resized.samples
            changed = 0
            outside = 0
            for index in range(0, len(samples1), original.n):
                if samples1[index:index + original.n] == samples2[index:index + original.n]:
                    continue
                changed += 1
                pixel = index // original.n
                point = pymupdf.Point((pixel % original.width + 0.5) / 2, (pixel // original.width + 0.5) / 2)
                if not any(point in (rect + (-1, -1, 1, 1)) for rect in bounds):
                    outside += 1
            assert outside == 0, (name, outside)
            region = pymupdf.Rect()
            for rect in bounds:
                region |= rect
            for word in before.get_text("words"):
                region |= pymupdf.Rect(word[:4])
            region = (region + (-10, -10, 10, 10)) & before.rect
            before.get_pixmap(dpi=144, clip=region, alpha=False).save(directory / f"{name}-source.png")
            after.get_pixmap(dpi=144, clip=region, alpha=False).save(directory / f"{name}-output.png")
            results.append({"case": name, "pages": len(source), "text_and_geometry_equal": True,
                            "image_placements_equal": True, "changed_pixels_144_dpi": changed,
                            "changed_pixels_outside_images": outside})
    (directory / "pdf-comparison.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
