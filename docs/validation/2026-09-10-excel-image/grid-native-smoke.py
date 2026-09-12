from pathlib import Path
import sys, tempfile, json
sys.path.insert(0,str(Path('excel-shrink/tests').resolve()))
from fixtures import write_workbook
from test_review import _explicit_grid_parts
from excel_shrink.core import process_workbook
folder=Path(tempfile.mkdtemp(prefix='karufile-grid-native-'))
source=folder/'input'/'grid.xlsx'; source.parent.mkdir()
output=folder/'output'/'grid.xlsx'; output.parent.mkdir()
write_workbook(source,parts=_explicit_grid_parts(shape_extent=True))
result=process_workbook(source,output)
assert result.status=='ADOPTED_LOSSY',result
summary={'normal':[{'relative_path':'grid.xlsx','source_path':str(source),'output_path':str(output)}]}
Path('docs/validation/2026-09-10-excel-image/grid-native-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
print(result)
