"""Developer experiment: original-derived pixel caps with unchanged workbook parts.

This does not change the product CLI or bypass its drawing/format protections.
All artifacts stay in a newly created local directory; no workbook DOM is saved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image, ImageDraw

from excel_shrink.core import ImagePlan, _encode_image, _inspect_image
from excel_shrink.drawing import inspect_drawings
from excel_shrink.package import (Budget, Protected, check_workbook, read_package,
                                  verify_candidate, write_candidate)


def capped_size(size: tuple[int, int], cap: int) -> tuple[int, int]:
    if type(cap) is not int or not 1 <= cap <= 10000:
        raise ValueError("cap must be an integer from 1 to 10000")
    if len(size) != 2 or any(type(n) is not int or n < 1 for n in size):
        raise ValueError("dimensions must be positive integers")
    longest = max(size)
    if longest <= cap:
        return size
    return tuple(max(1, (n * cap + longest // 2) // longest) for n in size)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare(source: Path, output: Path, caps: tuple[int, ...]) -> dict:
    source = source.resolve(strict=True)
    for cap in caps:
        capped_size((1, 1), cap)
    if not caps or len(set(caps)) != len(caps) or len(caps) > 8:
        raise ValueError("one to eight unique caps required")
    before = sha(source)
    package = read_package(source, Budget.start())
    check_workbook(package)
    drawings = inspect_drawings(package, Budget.start())
    output.mkdir(parents=True, exist_ok=False)
    assets = output / "assets"
    assets.mkdir()
    records = []
    originals = {}
    for index, part in enumerate(package.images, 1):
        try:
            fmt, size = _inspect_image(package.parts[part], package.types[part], part)
        except Protected:
            continue
        name = f"image-{index:03d}" + (".jpg" if fmt == "JPEG" else ".png")
        (assets / name).write_bytes(package.parts[part])
        originals[part] = (fmt, size, name)
    for cap in caps:
        budget = Budget.start()
        replacements = {}
        changes = []
        retained = []
        for part, (fmt, size, name) in originals.items():
            target = capped_size(size, cap)
            if part in drawings.protected or target == size:
                if target != size:
                    retained.append(dict(part=part, reason=drawings.protected[part]))
                continue
            plan = ImagePlan(part, fmt, size, target)
            data = _encode_image(package.parts[part], plan, budget)
            if data is not None:
                replacements[part] = data
                changes.append(dict(part=part, original=list(size), output=list(target)))
            else:
                retained.append(dict(part=part, reason="image_savings_or_quality_rejected"))
        destination = output / f"{source.stem}-{cap}px.xlsx"
        if replacements:
            write_candidate(package, replacements, destination, budget)
            verify_candidate(package, read_package(destination, budget), replacements)
            if destination.stat().st_size >= source.stat().st_size:
                shutil.copyfile(source, destination)
                replacements, changes = {}, []
        else:
            shutil.copyfile(source, destination)
        for part, (_, _, name) in originals.items():
            (assets / f"{cap}-{name}").write_bytes(replacements.get(part, package.parts[part]))
        records.append(dict(cap=cap, file=destination.name, bytes=destination.stat().st_size,
                            sha256=sha(destination), changed=len(changes), changes=changes,
                            retained_above_cap=retained,
                            non_image_parts_unchanged=True))
    if sha(source) != before:
        raise ValueError("source changed")
    images = [dict(part=part, name=name, size=list(size),
                   protection=drawings.protected.get(part, ""))
              for part, (_, size, name) in originals.items()]
    result = dict(source_bytes=source.stat().st_size, source_sha256=before,
                  images_total=len(package.images), images=images, variants=records,
                  recipe="pixel-cap-comparison-v1; JPEG quality85 4:4:4; LANCZOS; no upscale",
                  source_unchanged=True)
    (output / "comparison.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    # Static contact sheets use identical display dimensions for every candidate.
    # These are comparison enlargements, never workbook replacements.
    for entry in images:
        name = entry["name"]
        with Image.open(assets / name) as original:
            height = min(500, max(1, round(500 * original.height / original.width)))
            width = min(500, max(1, round(height * original.width / original.height)))
            canvas = Image.new("RGB", (500 * (len(caps) + 1), height + 32), "white")
            draw = ImageDraw.Draw(canvas)
            for col, cap in enumerate((None, *caps)):
                path = assets / (name if cap is None else f"{cap}-{name}")
                with Image.open(path) as image:
                    draw.text((col * 500 + 5, 8), f'{"Original" if cap is None else str(cap) + "px"} {image.width}x{image.height}', fill="black")
                    canvas.paste(image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS), (col * 500, 32))
            canvas.save(assets / (Path(name).stem + "-compare.png"))
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    html = '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>資格証画像のピクセル上限比較</title><style>
body{font-family:system-ui,sans-serif;margin:24px;color:#18232d;background:#f5f7f9}h1{font-size:24px}
table{border-collapse:collapse;background:white}td,th{padding:8px 18px;text-align:right;border-bottom:1px solid #ccc}
label{display:inline-block;margin:18px 20px 18px 0}select{padding:8px}.pair{display:flex;gap:24px;overflow:auto}
figure{margin:0;background:white;padding:12px}figcaption{margin-bottom:12px}.pair img{display:block;max-width:none}
p{max-width:1000px;line-height:1.7}a{color:#1261ab}</style>
<h1>資格証画像のピクセル上限比較</h1>
<p>原本からそれぞれ独立に縮小。Excel内の配置・表示寸法は保持しています。左右は同じ表示幅です。ブラウザーでの大きさは紙面の実寸ではありません。印刷比較には各Excelを同じ設定で印刷、または隣のPDFを使用してください。</p>
<table><thead><tr><th>上限</th><th>容量</th><th>削減率</th><th>変更画像</th><th>Excel</th><th>A4 PDF</th></tr></thead><tbody id="rows"></tbody></table>
<label>画像 <select id="picture"></select></label><label>上限 <select id="cap"></select></label>
<label>表示幅 <select id="zoom"><option value="380">380px</option><option value="700" selected>700px</option><option value="1000">1000px</option></select></label>
<p id="detail"></p><div class="pair"><figure><figcaption>元画像</figcaption><img id="original"></figure><figure><figcaption id="candidateLabel"></figcaption><img id="candidate"></figure></div>
<script>const data=PAYLOAD;
const byId=id=>document.getElementById(id);
for(const v of data.variants){const tr=document.createElement('tr');for(const value of [v.cap+'px',(v.bytes/1048576).toFixed(2)+' MiB',((1-v.bytes/data.source_bytes)*100).toFixed(2)+'%',v.changed+'/'+data.images_total]){const td=document.createElement('td');td.textContent=value;tr.append(td)}for(const ext of ['xlsx','pdf']){const td=document.createElement('td');const a=document.createElement('a');a.textContent=ext;a.href=ext==='xlsx'?v.file:'native-'+v.cap+'.pdf';td.append(a);tr.append(td)}byId('rows').append(tr);byId('cap').add(new Option(v.cap+'px',v.cap))}
data.images.forEach((p,i)=>byId('picture').add(new Option((i+1)+' / '+data.images.length+' — '+p.part,i)));
byId('cap').value='1000';function update(){const p=data.images[byId('picture').value],cap=byId('cap').value;byId('original').src='assets/'+p.name;byId('candidate').src='assets/'+cap+'-'+p.name;byId('candidateLabel').textContent='長辺上限 '+cap+'px';byId('detail').textContent=p.part+'　元画像 '+p.size.join(' × ')+'px'+(p.protection?'　保護: '+p.protection:'');for(const id of ['original','candidate'])byId(id).style.width=byId('zoom').value+'px'}
for(const id of ['picture','cap','zoom'])byId(id).onchange=update;update();</script></html>'''.replace("PAYLOAD", payload)
    (output / "comparison.html").write_text(html, encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--caps", nargs="+", type=int, default=[350, 700, 1000, 1400])
    args = parser.parse_args()
    report = compare(args.source, args.output, tuple(args.caps))
    print(json.dumps({k: report[k] for k in ("source_bytes", "images_total", "variants")}, ensure_ascii=True))
