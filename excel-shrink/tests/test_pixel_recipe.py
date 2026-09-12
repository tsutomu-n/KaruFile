from io import BytesIO
import csv
import zipfile

import pytest
from PIL import Image

from excel_shrink.cli import main
from excel_shrink.core import process_workbook
from excel_shrink.config import ExcelConfig
from fixtures import image_bytes, picture_anchor, write_workbook


@pytest.mark.parametrize("size,expected", [((1200, 600),(800,400)), ((600,1200),(400,800)), ((400,200),(400,200))])
def test_pixel_cap_and_same_size_jpeg_compression(tmp_path, size, expected):
    source, output = tmp_path/'source.xlsx', tmp_path/'out.xlsx'
    original = image_bytes(size=size)
    write_workbook(source, images={'xl/media/image1.jpeg': original})
    before = source.read_bytes()
    result = process_workbook(source, output, dpi=None, max_side=800, jpeg_quality=72)
    assert result.status == 'ADOPTED_LOSSY'
    with zipfile.ZipFile(source) as a, zipfile.ZipFile(output) as b:
        for name in a.namelist():
            if name != 'xl/media/image1.jpeg':
                assert a.read(name) == b.read(name)
        data = b.read('xl/media/image1.jpeg')
        assert len(data) < len(original)
        with Image.open(BytesIO(data)) as image:
            assert image.size == expected and image.format == 'JPEG'
            assert image.layer[0][1:3] == (1,1)  # 4:4:4
    assert source.read_bytes() == before


def test_small_png_not_recompressed_or_flattened(tmp_path):
    source, output = tmp_path/'source.xlsx', tmp_path/'out.xlsx'
    write_workbook(source, images={'xl/media/image1.png': image_bytes('PNG', (200,100), mode='RGBA')})
    result = process_workbook(source, output, dpi=None, max_side=800, jpeg_quality=72)
    assert result.status == 'PRESERVED_ORIGINAL'
    assert not output.exists()


@pytest.mark.parametrize('options', [dict(dpi=220,max_side=800),dict(dpi=None,max_side=99),
    dict(dpi=None,max_side=True),dict(jpeg_quality=39),dict(jpeg_quality=True)])
def test_invalid_recipe(tmp_path, options):
    with pytest.raises(ValueError):
        ExcelConfig(tmp_path/'in',tmp_path/'out',('*.xlsx',),**options)


def test_cli_default_and_dry_run_report(tmp_path):
    source = tmp_path/'in'
    source.mkdir()
    write_workbook(source/'sample.xlsx', images={'xl/media/image1.jpeg':image_bytes(size=(400,200))})
    output=tmp_path/'out'
    assert main(['run','--input',str(source),'--output',str(output),'--pattern','*.xlsx','--dry-run']) == 0
    assert not (output/'sample.xlsx').exists()
    with (tmp_path/'out.excel-report.dry-run.csv').open(encoding='utf-8-sig') as stream:
        row=next(csv.DictReader(stream))
    assert (row['schema_version'],row['dpi'],row['max_side'],row['jpeg_quality']) == ('3','','800','72')
    assert row['status'] == 'DRY_RUN'


def test_python_api_defaults_match_cli_and_compress_small_jpeg(tmp_path):
    config = ExcelConfig(tmp_path/'in',tmp_path/'out',('*.xlsx',))
    assert (config.dpi, config.max_side, config.jpeg_quality) == (None,800,72)
    legacy = ExcelConfig(tmp_path/'in',tmp_path/'out',('*.xlsx',),dpi=220)
    assert (legacy.dpi,legacy.max_side,legacy.jpeg_quality) == (220,None,85)
    source=tmp_path/'source.xlsx'
    write_workbook(source,images={'xl/media/image1.jpeg':image_bytes(size=(400,200))})
    implicit,explicit=tmp_path/'implicit.xlsx',tmp_path/'explicit.xlsx'
    assert process_workbook(source,implicit).status == 'ADOPTED_LOSSY'
    assert process_workbook(source,explicit,dpi=None,max_side=800,jpeg_quality=72).status == 'ADOPTED_LOSSY'
    assert implicit.read_bytes() == explicit.read_bytes()


def test_legacy_dpi_does_not_recompress_small_jpeg(tmp_path):
    source=tmp_path/'source.xlsx'
    write_workbook(source, images={'xl/media/image1.jpeg':image_bytes(size=(100,50))})
    assert process_workbook(source,tmp_path/'out.xlsx',dpi=220).status == 'PRESERVED_ORIGINAL'
