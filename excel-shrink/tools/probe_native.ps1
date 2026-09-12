param([Parameter(Mandatory=$true)][string]$RequestPath)
$ErrorActionPreference='Stop'
$request=Get-Content -LiteralPath $RequestPath -Raw -Encoding utf8 | ConvertFrom-Json
$excel=$null
$book=$null
$records=@()
function Release($obj) { if($null -ne $obj){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($obj)} }
function FileHash([string]$path) {
    $stream=[IO.File]::OpenRead($path)
    $hasher=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($hasher.ComputeHash($stream))).Replace('-','').ToLowerInvariant()}
    finally {$stream.Dispose();$hasher.Dispose()}
}
function ValueHash($value) {
    $data=[Text.Encoding]::UTF8.GetBytes(($value | ConvertTo-Json -Depth 8 -Compress))
    $hasher=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($hasher.ComputeHash($data))).Replace('-','').ToLowerInvariant()}
    finally {$hasher.Dispose()}
}
try {
    $excel=New-Object -ComObject Excel.Application
    $excel.Visible=$false
    $excel.DisplayAlerts=$false
    $excel.EnableEvents=$false
    $excel.AutomationSecurity=3
    $before=FileHash $request.source
    if($before.ToLowerInvariant() -ne $request.sha256){throw 'Source identity changed'}
    $book=$excel.Workbooks.Open($request.source,0,$true)
    if(-not $book.ReadOnly){throw 'Workbook was not opened read-only'}
    foreach($bounds in $request.sheets) {
        $sheet=$book.Worksheets.Item([int]$bounds.index)
        try {
            $cols=@()
            for($i=1;$i -le $bounds.columns;$i++) {
                $col=$sheet.Columns.Item($i)
                try {$cols += [ordered]@{index=$i;width_pt=$col.Width;column_width=$col.ColumnWidth}}
                finally {Release $col}
            }
            $rows=@()
            for($i=1;$i -le $bounds.rows;$i++) {
                $row=$sheet.Rows.Item($i)
                try {$rows += [ordered]@{index=$i;height_pt=$row.Height}}
                finally {Release $row}
            }
            $shapes=@()
            foreach($shape in $sheet.Shapes) {
                try {$shapes += [ordered]@{id=$shape.ID;width_pt=$shape.Width;height_pt=$shape.Height;left_pt=$shape.Left;top_pt=$shape.Top;rotation=$shape.Rotation;type=$shape.Type}}
                finally {Release $shape}
            }
            $used=$sheet.UsedRange
            try {
                if($used.Cells.CountLarge -gt 500000){throw 'Native oracle cell limit'}
                $records += [ordered]@{index=$bounds.index;columns=$cols;rows=$rows;shapes=$shapes;formula_hash=(ValueHash $used.Formula);value_hash=(ValueHash $used.Value2)}
            } finally {Release $used}
        } finally {Release $sheet}
    }
    $version=$excel.Version
    if($request.pdf){$book.ExportAsFixedFormat(0,$request.pdf,0,$false,$false,1,100,$false)}
    $book.Close($false)
    Release $book
    $book=$null
    $after=FileHash $request.source
    if($before -ne $after){throw 'Source changed during native inspection'}
    [ordered]@{version=$version;sha256=$after.ToLowerInvariant();sheets=$records} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $request.output -Encoding utf8
} finally {
    if($null -ne $book){$book.Close($false);Release $book}
    if($null -ne $excel){$excel.Quit();Release $excel}
    [GC]::Collect();[GC]::WaitForPendingFinalizers()
}
