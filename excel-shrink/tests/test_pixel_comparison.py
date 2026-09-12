"""Failure and preservation checks for the local pixel-cap experiment."""
import importlib.util
from pathlib import Path
import zipfile

import pytest

from fixtures import image_bytes, write_workbook

spec = importlib.util.spec_from_file_location("compare_pixel_caps", Path(__file__).parents[1] / "tools" / "compare_pixel_caps.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("size,cap,expected", [
    ((1109, 390), 700, (700, 246)), ((390, 1109), 700, (246, 700)),
    ((350, 350), 350, (350, 350)), ((100, 50), 350, (100, 50)),
    ((1, 10000), 350, (1, 350)),
])
def test_dimensions(size, cap, expected):
    assert module.capped_size(size, cap) == expected


@pytest.mark.parametrize("cap", [True, 0, -1, 10001, 350.0])
def test_invalid_cap(cap):
    with pytest.raises(ValueError):
        module.capped_size((1109, 390), cap)


def test_comparison_preserves_source_and_nonimage_parts(tmp_path):
    source = tmp_path / "input.xlsx"
    write_workbook(source, images={"xl/media/image1.jpeg": image_bytes(size=(800, 400))})
    original = source.read_bytes()
    output = tmp_path / "comparison"
    result = module.compare(source, output, (350, 1400))
    assert source.read_bytes() == original
    assert result["variants"][0]["changed"] == 1
    assert result["variants"][1]["changed"] == 0
    assert (output / "input-1400px.xlsx").read_bytes() == original
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(output / "input-350px.xlsx") as after:
        assert before.namelist() == after.namelist()
        assert [n for n in before.namelist() if before.read(n) != after.read(n)] == ["xl/media/image1.jpeg"]
    with pytest.raises(FileExistsError):
        module.compare(source, output, (350,))
    assert source.read_bytes() == original
