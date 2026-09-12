from pathlib import Path
import csv
import hashlib
import io
import json
import subprocess
import tempfile
import zipfile

from PIL import Image, ImageFilter

REPO = Path.cwd()
WORK = Path(tempfile.mkdtemp(prefix="karufile-excel-root-smoke-"))
SRC, OUT = WORK / "input", WORK / "output"
SRC.mkdir()
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
X = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"


def rels(*values):
    return f'<Relationships xmlns="{REL}">' + "".join(
        f'<Relationship Id="{rid}" Type="{R}/{kind}" Target="{target}"/>'
        for rid, kind, target in values
    ) + "</Relationships>"


def book(path, image_format, size):
    image = Image.effect_noise(size, 70).filter(ImageFilter.GaussianBlur(2)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **({"quality": 97, "subsampling": 0} if image_format == "JPEG" else {}))
    ext, mime = ("jpg", "jpeg") if image_format == "JPEG" else ("png", "png")
    parts = {
        "[Content_Types].xml": f'''<Types xmlns="{CT}">
        <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
        <Default Extension="xml" ContentType="application/xml"/>
        <Default Extension="{ext}" ContentType="image/{mime}"/>
        <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
        <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
        <Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>
        </Types>''',
        "_rels/.rels": rels(("rId1", "officeDocument", "xl/workbook.xml")),
        "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": rels(("rId1", "worksheet", "worksheets/sheet1.xml")),
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{S}" xmlns:r="{R}"><sheetData><row r="1"><c r="A1"><f>1+2</f><v>3</v></c></row></sheetData><drawing r:id="rId1"/></worksheet>',
        "xl/worksheets/_rels/sheet1.xml.rels": rels(("rId1", "drawing", "../drawings/drawing1.xml")),
        "xl/drawings/_rels/drawing1.xml.rels": rels(("rId1", "image", f"../media/image1.{ext}")),
        "xl/drawings/drawing1.xml": f'''<xdr:wsDr xmlns:xdr="{X}" xmlns:a="{A}" xmlns:r="{R}">
        <xdr:oneCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>2</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
        <xdr:ext cx="914400" cy="685800"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="1" name="Photograph"/><xdr:cNvPicPr/></xdr:nvPicPr>
        <xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>
        <xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>''',
        f"xl/media/image1.{ext}": buffer.getvalue(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def invoke(arguments, label, expected):
    command = ["uv", "run", "--script", "karufile.py", "-i", str(SRC), "-o", str(OUT), *arguments]
    completed = subprocess.run(command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               encoding="utf-8", errors="replace", timeout=180)
    (WORK / f"{label}.log").write_text(completed.stdout, encoding="utf-8")
    assert completed.returncode == expected, (label, completed.returncode, completed.stdout)
    return completed.returncode


book(SRC / "good" / "png.xlsx", "PNG", (1200, 900))
book(SRC / "good" / "jpeg.xlsx", "JPEG", (1200, 900))
book(SRC / "good" / "small.xlsx", "PNG", (40, 30))
(SRC / "good" / "~$ignored.xlsx").write_bytes(b"Office lock")
originals = {str(path.relative_to(SRC)): digest(path) for path in SRC.rglob("*") if path.is_file()}
invoke(["--excel-pattern", "good/*.xlsx"], "normal", 0)
normal = records(Path(f"{OUT}.excel-report.csv"))
assert len(normal) == 3
assert [row["status"] for row in normal] == ["ADOPTED_LOSSY", "ADOPTED_LOSSY", "PRESERVED_ORIGINAL"], normal
assert all(row["dpi"] == "220" for row in normal)
for row in normal:
    source, output = Path(row["source_path"]), Path(row["output_path"])
    with zipfile.ZipFile(source) as left, zipfile.ZipFile(output) as right:
        actual = [name for name in left.namelist() if left.read(name) != right.read(name)]
        assert actual == json.loads(row["changed_parts"])
        for name in actual:
            with Image.open(io.BytesIO(right.read(name))) as image:
                assert image.size == (220, 165), image.size
before = {str(path): digest(path) for path in OUT.rglob("*") if path.is_file()}
normal_report_hash = digest(Path(f"{OUT}.excel-report.csv"))
invoke(["--excel-pattern", "good/*.xlsx", "--excel-dpi", "150", "--dry-run"], "dry-run", 0)
assert before == {str(path): digest(path) for path in OUT.rglob("*") if path.is_file()}
assert digest(Path(f"{OUT}.excel-report.csv")) == normal_report_hash
dry = records(Path(f"{OUT}.excel-report.dry-run.csv"))
assert [row["status"] for row in dry] == ["DRY_RUN", "DRY_RUN", "DRY_RUN_PRESERVED"]
assert all(row["output_size"] == row["output_sha256"] == "" and row["changed_parts"] == "[]" for row in dry)
invoke(["--excel-pattern", "good/*.xlsx", "--preset", "compact"], "compact-rerun", 0)
assert {str(path.relative_to(SRC)): digest(path) for path in SRC.rglob("*") if path.is_file()} == originals
(SRC / "errors").mkdir()
(SRC / "errors" / "broken.xlsx").write_bytes(b"invalid ZIP workbook")
(SRC / "errors" / "encrypted.xlsx").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1encrypted-office-content")
(OUT / "errors").mkdir()
(OUT / "errors" / "broken.xlsx").write_bytes(b"prior completed workbook")
invoke(["--excel-pattern", "errors/*.xlsx"], "errors-and-preservation", 1)
errors = records(Path(f"{OUT}.excel-report.csv"))
assert [row["status"] for row in errors] == ["ERROR", "PRESERVED_ORIGINAL"]
assert (OUT / "errors" / "broken.xlsx").read_bytes() == b"prior completed workbook"
assert digest(OUT / "errors" / "encrypted.xlsx") == digest(SRC / "errors" / "encrypted.xlsx")
assert all(digest(SRC / name) == expected for name, expected in originals.items())
summary = {"work_dir": str(WORK), "normal": normal, "dry_run": dry, "errors": errors,
           "checks": ["PNG/JPEG 1200x900 -> 220x165", "small copied byte-exact", "all other parts equal",
                      "normal/dry/compact real root CLI", "normal report and outputs retained by dry-run",
                      "invalid input error preserves previous output", "independent protected input copied", "all original SHA unchanged"]}
(WORK / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"work_dir": str(WORK), "normal": [{"file": row["relative_path"], "status": row["status"], "before": row["source_size"], "after": row["output_size"]} for row in normal], "checks": summary["checks"]}, ensure_ascii=False, indent=2))
