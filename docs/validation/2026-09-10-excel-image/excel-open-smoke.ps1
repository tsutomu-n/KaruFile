param(
    [Parameter(Mandatory = $true)][string]$SummaryPath,
    [Parameter(Mandatory = $true)][string]$EvidenceDir
)
$ErrorActionPreference = 'Stop'
$summary = Get-Content -LiteralPath $SummaryPath -Raw | ConvertFrom-Json
$null = New-Item -ItemType Directory -Path $EvidenceDir -Force
$EvidenceDir = (Resolve-Path -LiteralPath $EvidenceDir).Path
$records = [System.Collections.Generic.List[object]]::new()
$excel = $null
$book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.EnableEvents = $false
    $excel.AutomationSecurity = 3
    foreach ($item in $summary.normal) {
        foreach ($side in @('source', 'output')) {
            $path = if ($side -eq 'source') { $item.source_path } else { $item.output_path }
            $before = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
            # UpdateLinks=0, ReadOnly=true; CorruptLoad defaults to xlNormalLoad.
            $book = $excel.Workbooks.Open($path, 0, $true)
            $sheet = $book.Worksheets.Item(1)
            $shapes = @()
            foreach ($shape in $sheet.Shapes) {
                $shapes += [ordered]@{
                    name = $shape.Name; width_points = $shape.Width; height_points = $shape.Height
                    left_points = $shape.Left; top_points = $shape.Top; type = $shape.Type
                }
                $null = [Runtime.InteropServices.Marshal]::ReleaseComObject($shape)
            }
            $pdf = Join-Path $EvidenceDir (([IO.Path]::GetFileNameWithoutExtension($path)) + '-' + $side + '.pdf')
            $sheet.ExportAsFixedFormat(0, $pdf)
            $record = [ordered]@{
                relative_path = $item.relative_path; side = $side; excel_version = $excel.Version
                opened_read_only = $book.ReadOnly; worksheet_count = $book.Worksheets.Count
                formula_a1 = $sheet.Range('A1').Formula; value_a1 = $sheet.Range('A1').Value2
                shapes = $shapes; exported_pdf = $pdf; sha256_before = $before
            }
            $null = [Runtime.InteropServices.Marshal]::ReleaseComObject($sheet)
            $book.Close($false)
            $null = [Runtime.InteropServices.Marshal]::ReleaseComObject($book)
            $book = $null
            $record.sha256_after = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
            if ($record.sha256_before -ne $record.sha256_after) { throw "Input changed: $path" }
            $records.Add($record)
        }
    }
    foreach ($item in $summary.normal) {
        $pair = @($records | Where-Object relative_path -EQ $item.relative_path)
        foreach ($field in @('formula_a1', 'value_a1', 'worksheet_count', 'shapes')) {
            if (($pair[0].$field | ConvertTo-Json -Depth 8 -Compress) -cne ($pair[1].$field | ConvertTo-Json -Depth 8 -Compress)) {
                throw "Excel source/output mismatch: $($item.relative_path) $field"
            }
        }
    }
    $records | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceDir 'excel-open-summary.json') -Encoding utf8
    Write-Output "PASS: $($records.Count) synthetic workbooks opened read-only in Excel; formulas and shape geometry match; PDFs exported; file SHA unchanged."
}
finally {
    if ($null -ne $book) { $book.Close($false); $null = [Runtime.InteropServices.Marshal]::ReleaseComObject($book) }
    if ($null -ne $excel) { $excel.Quit(); $null = [Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
