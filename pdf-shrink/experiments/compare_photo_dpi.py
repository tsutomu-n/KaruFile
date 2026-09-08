"""CP-012: independent 200/180 DPI photo trial, never used by the product CLI.

Uses the current photo transform and validation, changing only the experimental
target DPI. Requires existing qpdf, original PDFs and corresponding 200 DPI PDFs.
The output directory must be new. No product defaults or state are changed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

import pymupdf as fitz

from pdf_shrink.config import LossyOptions, ScanOptions, photo_lossy_options
from pdf_shrink.inspect_pdf import inspect_file, _effective_image_dpis
from pdf_shrink.models import OptimizationMode
from pdf_shrink.transform import optimize_lossy
from pdf_shrink.validate import validate


@dataclass(frozen=True)
class TrialPhotoOptions(LossyOptions):
    """Allow two experimental targets without modifying production's guard."""

    def __post_init__(self) -> None:
        expected = asdict(photo_lossy_options())
        actual = asdict(self)
        if actual.pop("dpi_target") not in (180, 200):
            raise ValueError("trial supports only 180 and 200 DPI")
        expected.pop("dpi_target")
        if actual != expected:
            raise ValueError("all non-DPI options must match the production photo recipe")


def recipe(dpi: int) -> TrialPhotoOptions:
    values = asdict(photo_lossy_options())
    values["dpi_target"] = dpi
    return TrialPhotoOptions(**values)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot(roots: list[Path]) -> dict[str, str]:
    files = {p.resolve() for root in roots for p in root.rglob("*") if p.is_file()}
    return {str(p): sha(p) for p in sorted(files)}


def placements(page: fitz.Page) -> list[tuple]:
    return [(tuple(i["bbox"]), tuple(i["transform"])) for i in page.get_image_info()]


def structure_check(source: Path, candidate: Path, *, exact_pixels: bool = False) -> dict:
    """Check all pages; IDs/xrefs can be renumbered during PDF serialization."""
    with fitz.open(source) as src, fitz.open(candidate) as dst:
        if src.page_count != dst.page_count:
            raise RuntimeError("page count mismatch")
        for a, b in zip(src, dst):
            if (a.rotation, a.mediabox, a.cropbox, a.rect) != (b.rotation, b.mediabox, b.cropbox, b.rect):
                raise RuntimeError(f"page {a.number + 1}: geometry mismatch")
            if a.get_text() != b.get_text() or a.get_drawings() != b.get_drawings():
                raise RuntimeError(f"page {a.number + 1}: text/path mismatch")
            if placements(a) != placements(b):
                raise RuntimeError(f"page {a.number + 1}: image placement mismatch")
            if exact_pixels:
                ai, bi = a.get_image_info(xrefs=True), b.get_image_info(xrefs=True)
                for x, y in zip(ai, bi):
                    if (x["width"], x["height"], x["digest"]) != (y["width"], y["height"], y["digest"]):
                        raise RuntimeError("reference 200 DPI image pixels differ")
                ap = a.get_pixmap(dpi=300, colorspace=fitz.csRGB, alpha=False)
                bp = b.get_pixmap(dpi=300, colorspace=fitz.csRGB, alpha=False)
                if (ap.width, ap.height, ap.samples) != (bp.width, bp.height, bp.samples):
                    raise RuntimeError("reference 200 DPI rendered RGB differs")
        return {"pages": src.page_count, "geometry_text_paths_placements_equal": True,
                "image_pixels_and_300dpi_rgb_equal": exact_pixels}


def image_inventory(path: Path) -> list[dict]:
    with fitz.open(path) as doc:
        return [{"page": p.number + 1, "xref": i["xref"],
                 "width": i["width"], "height": i["height"],
                 "bbox": i["bbox"], "transform": i["transform"],
                 "placed_dpi": _effective_image_dpis(i)}
                for p in doc for i in p.get_image_info(xrefs=True)]


def render_views(paths: dict[str, Path], folder: Path) -> list[dict]:
    """All pages at 144 DPI; every placed photo at 300 DPI for fine detail."""
    assets = folder / "assets"
    assets.mkdir()
    views = []
    with fitz.open(paths["original"]) as source:
        for page in source:
            regions = [("ページ全体", page.rect, 144)]
            regions += [(f"写真 {n}", fitz.Rect(info["bbox"]) & page.rect, 300)
                        for n, info in enumerate(page.get_image_info(), 1)]
            for region_index, (label, rect, dpi) in enumerate(regions):
                if rect.is_empty:
                    raise RuntimeError("empty comparison region")
                views.append({"page": page.number + 1, "label": label, "region": region_index,
                              "rect": list(rect), "render_dpi": dpi,
                              "css_width": rect.width * 96 / 72, "images": {}})
    for kind, path in paths.items():
        with fitz.open(path) as doc:
            for view in views:
                filename = f"{kind}-p{view['page']:02d}-r{view['region']}.png"
                pix = doc[view["page"] - 1].get_pixmap(
                    dpi=view["render_dpi"], clip=fitz.Rect(view["rect"]),
                    colorspace=fitz.csRGB, alpha=False,
                )
                pix.save(assets / filename)
                if "pixel_width" in view and (view["pixel_width"], view["pixel_height"]) != (pix.width, pix.height):
                    raise RuntimeError("comparison render dimensions differ")
                view["pixel_width"], view["pixel_height"] = pix.width, pix.height
                view["images"][kind] = f"{folder.name}/assets/{filename}"
    return views


def run_case(source: Path, reference: Path, folder: Path, qpdf: Path, label: str) -> dict:
    folder.mkdir()
    result = {"label": label, "source": str(source), "source_sha256": sha(source),
              "original_bytes": source.stat().st_size, "source_images": image_inventory(source),
              "reference_200dpi": {"path": str(reference), "bytes": reference.stat().st_size,
                                   "sha256": sha(reference)}, "candidates": {}}
    paths = {"original": source}
    for dpi in (200, 180):
        started = time.perf_counter()
        options = recipe(dpi)
        inspection = inspect_file(source, ScanOptions(), safe=False, lossy_options=options)
        if not inspection.ok or inspection.mode != OptimizationMode.LOSSY:
            raise RuntimeError(f"inspection did not allow photo trial: {inspection}")
        if source.stat().st_size < 256 * 1024:
            raise RuntimeError("trial source below production skip threshold")
        candidate = folder / f"{dpi}dpi.pdf"
        changed = optimize_lossy(source, candidate, options)
        generation_seconds = time.perf_counter() - started
        check_started = time.perf_counter()
        ok, reason = validate(source, candidate, qpdf, enhanced=True, detail=True)
        structure = structure_check(source, candidate)
        if dpi == 200:
            result["reference_200dpi"]["comparison"] = structure_check(reference, candidate, exact_pixels=True)
        size = candidate.stat().st_size
        saved = source.stat().st_size - size
        record = {"file": f"{folder.name}/{candidate.name}", "options": asdict(options),
                  "inspection": asdict(inspection), "changed_images": changed,
                  "bytes": size, "sha256": sha(candidate), "saved_bytes": saved,
                  "saved_percent": saved / source.stat().st_size * 100,
                  "generation_seconds": generation_seconds,
                  "validation_seconds": time.perf_counter() - check_started,
                  "validation_ok": ok, "validation_reason": reason,
                  "structure": structure, "images": image_inventory(candidate),
                  "meets_photo_size_gate": saved >= 64 * 1024 and saved / source.stat().st_size >= .05}
        result["candidates"][str(dpi)] = record
        paths[str(dpi)] = candidate
        print(f"{label} {dpi} DPI: {size:,} bytes; validation={ok} {reason}", flush=True)
        write_json(folder / "evidence.json", result)
    a, b = (result["candidates"][str(dpi)]["bytes"] for dpi in (200, 180))
    result["additional_saved_bytes"] = a - b
    result["additional_saved_percent_of_200dpi"] = (a - b) / a * 100
    result["views"] = render_views(paths, folder)
    write_json(folder / "evidence.json", result)
    return result


HTML = r'''<!doctype html>
<html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>写真の解像度比較 — 200 / 180 DPI</title>
<style>
:root{font:15px/1.6 "Yu Gothic UI",Meiryo,sans-serif;color:#172a36;background:#f3f5f5;color-scheme:light}
*{box-sizing:border-box}body{margin:0}header,main{max-width:1500px;margin:auto;padding:24px 32px}
header{padding-bottom:8px}h1{font-size:28px;margin:4px 0}h2{font-size:19px;margin:0 0 10px}
.eyebrow{font-size:12px;letter-spacing:.15em;color:#52716b}p{margin:6px 0 14px}.muted{color:#53636d}
table{border-collapse:collapse;width:100%;background:#fff;margin:14px 0}td,th{text-align:right;padding:12px 16px;border-bottom:1px solid #dfe6e6;font-variant-numeric:tabular-nums}th:first-child,td:first-child{text-align:left}th{font-size:13px;color:#52636a}a{color:#075f6d;text-underline-offset:3px}
.toolbar{background:#fff;border:1px solid #dbe2e3;border-radius:10px;padding:14px;display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:14px 0}
label{display:flex;gap:7px;align-items:center}button,select{font:inherit;border:1px solid #b9c8cb;border-radius:6px;background:#fff;padding:7px 12px;color:inherit}button{cursor:pointer}button.active{background:#14675e;border-color:#14675e;color:#fff}button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid #f1bb4c;outline-offset:2px}
.buttons{display:flex;gap:5px}.stage{height:70vh;min-height:420px;overflow:auto;background:#dbe1e2;border:1px solid #bdcace;border-radius:10px;padding:20px}
.panels{display:flex;align-items:flex-start;gap:20px;width:max-content;min-width:100%;justify-content:center}.panel{flex:none}.caption{padding:7px 10px;background:#fff;border-bottom:1px solid #dbe1e2;font-weight:600;position:sticky;top:-20px}.panel img{display:block;background:white;box-shadow:0 2px 10px #243e4220;height:auto}.note{font-size:13px;margin-top:12px}footer{padding:20px 0;color:#53636d;font-size:13px}
@media(max-width:700px){header,main{padding:16px}h1{font-size:23px}.tablewrap{overflow:auto}td,th{padding:10px;white-space:nowrap}.toolbar{gap:9px}.stage{padding:10px}.panels{justify-content:flex-start}}
</style>
<header><div class="eyebrow">KaruFile / 写真DPI比較試験</div><h1>表示サイズはそのまま。写真の細部を比べる。</h1>
<p class="muted">原本から200 DPI・180 DPIをそれぞれ生成。どちらもJPEG品質80。通常CLIの200 DPI設定は変更していません。</p></header>
<main><div class="tablewrap"><table><thead><tr><th>資料</th><th>原本</th><th>200 DPI</th><th>180 DPI</th><th>200 → 180の追加削減</th></tr></thead><tbody id="summary"></tbody></table></div>
<p class="note" id="validation"></p><h2>同じ位置・倍率で切り替える</h2>
<p>黒板の文字や表面の細部は、表示範囲を「写真」にして比較してください。写真領域は300 DPIで描画しています。キー <b>1 / 2 / 3</b> でも原本・200・180を切り替えられます。</p>
<div class="toolbar"><label>資料 <select id="book"></select></label><label>ページ <select id="page"></select></label><label>表示範囲 <select id="region"></select></label>
<div class="buttons" id="variants"><button data-kind="original">1 原本</button><button data-kind="200" class="active">2 200 DPI</button><button data-kind="180">3 180 DPI</button></div>
<label><input type="checkbox" id="side">3枚を並べる</label><label>倍率 <input type="range" id="zoom" min="50" max="250" step="25" value="100"><output id="zoomValue">100%</output></label></div>
<div class="stage" id="stage"><div class="panels" id="panels"></div></div>
<p class="note">100%はPDFの1 inchを96 CSS pxで表示します。実際の画面上の物理寸法は端末設定に依存します。3候補の表示寸法は共通です。ページ全体は144 DPI描画、写真範囲は300 DPI描画。拡大表示は画素情報を増やしません。</p>
<footer>写真の画素は変わる非可逆比較です。自動検査の合格は、すべての細字の可読性・OCR精度・全ビューアー互換性の保証ではありません。生成と検査は各1回の観測で、速度のベンチマークではありません。<br><a href="comparison.json">検証結果 JSON</a> · <a href="comparison.md">比較記録</a></footer></main>
<script>
const data=__DATA__, $=id=>document.getElementById(id), names={original:'原本',200:'200 DPI / 品質80',180:'180 DPI / 品質80'};
const fmt=n=>(n/1e6).toFixed(3)+' MB';let selected='200';
$('summary').innerHTML=data.cases.map(c=>`<tr><td>${c.label}</td><td>${fmt(c.original_bytes)}</td>${['200','180'].map(k=>`<td><a href="${c.candidates[k].file}">${fmt(c.candidates[k].bytes)} ↗</a></td>`).join('')}<td>${(c.additional_saved_bytes/1024).toFixed(1)} KiB / ${c.additional_saved_percent_of_200dpi.toFixed(2)}%</td></tr>`).join('');
$('validation').textContent=data.all_valid?'4候補すべて自動検査合格。全17ページの形状・抽出文字・描画パス・画像配置は原本と一致。200 DPI再生成版は既存出力と全ページ300 DPI RGBが一致。':'未合格の候補があります。comparison.jsonの検証結果を確認してください。';
data.cases.forEach((c,i)=>$('book').add(new Option(c.label,i)));
function current(){return data.cases[Number($('book').value)]}
function pages(){const c=current();$('page').replaceChildren();[...new Set(c.views.map(v=>v.page))].forEach(p=>$('page').add(new Option(p+' / '+c.candidates['200'].structure.pages,p)));regions()}
function regions(){$('region').replaceChildren();current().views.filter(v=>v.page===Number($('page').value)).forEach(v=>$('region').add(new Option(v.label,v.region)));render()}
function render(){const view=current().views.find(v=>v.page===Number($('page').value)&&v.region===Number($('region').value));const kinds=$('side').checked?['original','200','180']:[selected];const width=view.css_width*Number($('zoom').value)/100;$('zoomValue').value=$('zoom').value+'%';
 const stage=$('stage'),left=stage.scrollLeft,top=stage.scrollTop;
 $('panels').replaceChildren(...kinds.map(k=>{const panel=document.createElement('div');panel.className='panel';const cap=document.createElement('div');cap.className='caption';cap.textContent=names[k];const img=document.createElement('img');img.src=view.images[k];img.alt=`${current().label} ${view.page}ページ ${view.label} ${names[k]}`;img.width=view.pixel_width;img.height=view.pixel_height;img.style.width=width+'px';panel.append(cap,img);return panel}));stage.scrollLeft=left;stage.scrollTop=top;
 document.querySelectorAll('[data-kind]').forEach(b=>{b.classList.toggle('active',b.dataset.kind===selected);b.setAttribute('aria-pressed',String(b.dataset.kind===selected))})}
$('book').onchange=pages;$('page').onchange=regions;$('region').onchange=render;$('side').onchange=render;$('zoom').oninput=render;
document.querySelectorAll('[data-kind]').forEach(b=>b.onclick=()=>{selected=b.dataset.kind;render()});document.addEventListener('keydown',e=>{if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName))return;const k={'1':'original','2':'200','3':'180'}[e.key];if(k){selected=k;render()}});pages();
</script></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--qpdf", type=Path, required=True)
    parser.add_argument("--protect", type=Path, action="append", default=[])
    args = parser.parse_args()
    args.input, args.reference, args.output, args.qpdf = (p.resolve() for p in (args.input, args.reference, args.output, args.qpdf))
    protected_roots = [args.input, args.reference, *(p.resolve() for p in args.protect)]
    for root in protected_roots:
        if not root.is_dir():
            raise ValueError(f"protected directory missing: {root}")
        if args.output == root or args.output.is_relative_to(root) or root.is_relative_to(args.output):
            raise ValueError("output must be separate from every protected directory")
    if not args.qpdf.is_file():
        raise ValueError("qpdf must already exist")
    cases = [("site", "現地写真", "2.現地写真（西牧）.pdf"),
             ("sampling", "採取写真", "5.採取写真（西牧）.pdf")]
    for _, _, name in cases:
        if not (args.input / name).is_file() or not (args.reference / name).is_file():
            raise ValueError(f"source or 200 DPI reference missing: {name}")
    args.output.mkdir(parents=True, exist_ok=False)
    before = snapshot(protected_roots)
    write_json(args.output / "protected-before.json", before)
    repo = Path(__file__).resolve().parents[2]
    code_files = [Path(__file__).resolve(), *(repo / "pdf-shrink/src/pdf_shrink").glob("*.py")]
    result = {"created_utc": datetime.now(timezone.utc).isoformat(), "pymupdf": fitz.VersionBind,
              "qpdf": {"path": str(args.qpdf), "sha256": sha(args.qpdf), "version": subprocess.check_output([str(args.qpdf), "--version"], text=True).strip()},
              "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
              "code_sha256": {str(p.relative_to(repo)): sha(p) for p in code_files},
              "recipe": "independent originals; existing photo transform; JPEG q80; no extra qpdf optimization",
              "validation": "unchanged production 72 DPI global/local and bounded 300 DPI detail; exact geometry/text/paths/placements",
              "cases": []}
    try:
        for slug, label, name in cases:
            result["cases"].append(run_case(args.input / name, args.reference / name, args.output / slug, args.qpdf, label))
            write_json(args.output / "comparison.json", result)
    finally:
        after = snapshot(protected_roots)
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        result["protected_files"] = len(before)
        result["protected_unchanged"] = not changed
        result["protected_changes"] = changed
        write_json(args.output / "protected-after.json", after)
        write_json(args.output / "comparison.json", result)
        if changed:
            raise RuntimeError(f"protected files changed: {changed}")
    result["all_valid"] = all(c["validation_ok"] and c["meets_photo_size_gate"] for book in result["cases"] for c in book["candidates"].values())
    write_json(args.output / "comparison.json", result)
    # Escape '<' to keep source labels from terminating the inline JSON script.
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    (args.output / "比較.html").write_text(HTML.replace("__DATA__", payload), encoding="utf-8")
    lines = ["# 写真200 / 180 DPI比較", "", "原本から独立生成、JPEG品質80、配置寸法維持。通常CLIは未変更。", "",
             "| 資料 | 原本bytes | 200 DPI bytes | 180 DPI bytes | 追加削減bytes / 対200 DPI |", "|---|---:|---:|---:|---:|"]
    for b in result["cases"]:
        lines.append(f"| {b['label']} | {b['original_bytes']:,} | {b['candidates']['200']['bytes']:,} | {b['candidates']['180']['bytes']:,} | {b['additional_saved_bytes']:,} / {b['additional_saved_percent_of_200dpi']:.2f}% |")
    for b in result["cases"]:
        for dpi, c in b["candidates"].items():
            lines.append(f"\n{b['label']} {dpi} DPI: 生成 {c['generation_seconds']:.2f}秒、検査/照合 {c['validation_seconds']:.2f}秒、変更 {c['changed_images']}画像、検証 {c['validation_ok']} {c['validation_reason']}。")
    lines += ["", f"保護対象 {len(before)}ファイルのSHA-256不変。既存200 DPIとの画像画素・全ページ300 DPI RGB一致。",
              "全ページの形状・抽出文字・描画パス・画像配置一致。写真自体の画素は非可逆に変化する。",
              "自動検査の合格は細字の可読性、OCR精度、全ビューアーの互換性を保証しない。",
              "描画はPyMuPDF 1.28.2を使用。Popplerは環境に未検出。別ビューアーでの主観比較は完成PDFでも実施できる。",
              "時間は各1回の観測。200 DPIの検査時間には既存出力との追加照合を含むため速度比較には使わない。"]
    (args.output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Completed: {args.output}; all_valid={result['all_valid']}; protected={len(before)}", flush=True)
    return 0 if result["all_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
