# KaruFile repository instructions

## Sources of truth

1. Executable behavior: code, tests, project configuration, and lockfiles.
2. End-user procedures and safety: `MANUAL.md`.
3. Exact product contracts: `docs/REFERENCE.md`.
4. Component README files and `orchestrator/docs/shrink_orchestrator_design.md`.
5. Architecture diagrams and historical ExecPlans.

Use `docs/README.md` for documentation roles and history. The manual and reference cover different
details; resolve any disagreement against executable behavior rather than silently choosing one.

When documentation conflicts with executable behavior, verify the code and tests, then update every affected
document in the same change. Do not invent setup, behavior, guarantees, or validation results.

## Architecture

- `karufile.py`: normal user entry point; requires Python 3.13 or later.
- `orchestrator/shrink_all.py`: validates paths and input/output identities, runs PDF then images and explicitly selected Excel,
  and runs video only for `compact`. Validates reports/manifests against current inputs and outputs
  before combining results; do not replace this with stdout parsing or approximate counts.
- `pdf-shrink/`: only PDF processor; owns PDF state and reports.
- `media-shrink-tool/`: only standalone-image processor; outputs JPEG and owns image error reports/manifests.
- `excel-shrink/`: only Excel processor; owns bounded OOXML parsing, image resizing, reports and temporary workspace.
- `video-shrink/`: only standalone-video processor; owns video state and reports and calls external FFmpeg tools.

Do not move PDF, Excel or video processing into `media-shrink-tool`. HDR/interlaced/complex-stream video
conversion, preservation of VFR timing, deduplication, perceptual hashing, source deletion, and a GUI
are outside the supported scope. Default compact video accepts VFR input and converts it to CFR;
explicit video safe mode rejects VFR input.

The root CLI's `standard` preset does not discover or copy videos. The standalone video CLI's
`standard` preset copies discovered videos without transcoding; preserve this distinction.

## Development layout

- Run repository commands from the root unless a command explicitly changes directory.
- Each processor has its own `pyproject.toml`, `uv.lock`, and local `.venv`; there is no root Python project.
  The root entry point uses inline script metadata; the orchestrator uses the standard library.
- Root/PDF/Excel/video require Python 3.13 or later; the image component declares Python 3.11 or later.
- PDF uses PyMuPDF and external qpdf; video uses external FFmpeg/ffprobe. Do not assume Python dependency
  installation provides these executables. FFmpeg/ffprobe are not downloaded or bundled by this project.
- Keep lockfiles, `.python-version`, ExecPlans, architecture HTML, and visual-check evidence versioned.
  `.gitignore` excludes default output trees, runtime state/reports, and Python build/cache artifacts.
  Add machine-specific custom output paths to `.git/info/exclude`; do not broadly ignore media extensions.

## Required contracts

- Never modify or delete input files.
- Write completed files to a separate output tree while preserving relative directories.
- Reject equal or nested input/output paths and unsafe symlink, junction, or hard-link destinations.
- Publish outputs and reports through validated temporary files and `os.replace()` where implemented.
- Continue independent files after a per-file failure; return nonzero when any required result fails.
- Root defaults: output `<input>_軽量化`, preset `standard`, PDF workers `2`, image workers `4`, video workers `1`.
- The standalone image CLI defaults to `<input>_resized`; the standalone video CLI requires `--output`.
- Excel is opt-in through repeatable root `--excel-pattern` / standalone `--pattern` using the photo glob rules.
  Discover only selected `.xlsx`, skip names starting `~$`, and never discover/copy Excel by default.
  CLI defaults in both presets: long side 800px and JPEG quality72/subsampling0; PNG preserves alpha, no upscale.
  ExcelConfig/process_workbook also resolve omitted sizing/quality to 800px/72. Only explicit DPI selects legacy sizing.
  Root `--excel-max-side` / standalone `--max-side` accepts 100..10000. JPEG quality accepts 40..95.
  Explicit `--excel-dpi` / `--dpi` selects legacy 150..300 DPI sizing, excludes max-side, defaults quality85.
  All explicit root Excel settings require patterns. Pixel mode recompresses even JPEGs within the cap;
  DPI mode and PNG require downsizing. Adopt only smaller image bytes. Keep placement/format protections in both modes.
  JPEG unknown/duplicate metadata, metadata after scans, and trailing data protect that image; split ICC is
  validated separately. Preserve supported ICC/EXIF/comments and PNG metadata payload bytes; do not sanitize.
  Preserve displayed dimensions. DPI sizing accounts for inward crop and maximum needs across shared references.
  Pixel sizing rounds each axis to nearest integer (half up), min1px; protected/rejected images can exceed the cap.
  Support oneCellAnchor/absoluteAnchor and same-cell twoCellAnchor with exact offset differences.
  Multi-cell twoCellAnchor requires one worksheet owner and verified regular 11pt Calibri/Yu Gothic Normal font.
  Windows GDI measures digits, validates actual face/style/size/charset/MDW and hashes font data; no Excel runtime.
  Calibri theme Latin or Yu Gothic EA/Jpan must match. Non-Windows retains ISO Calibri only.
  Explicit/defaultColWidth or baseColWidth=8 defaults are supported. Saved bestFit requires width/customWidth=true.
  No hidden/collapsed/border-adjusted dimensions or formula/RTL/custom sheet views.
  Widths are >0 and <=255; heights >0 and <=409 pt, integral 96-DPI pixels. Require customHeight=true,
  or defaultRowHeight on empty unstyled rows without explicit ht or nonzero column styles; never infer autoFit.
  Permit x14ac:dyDescent only from zero through the row pixel height. Cap each grid span at 1024 cells.
  Use MDW 7/8 and floor(((256*width+floor(128/MDW))*MDW)/256); default base8 rounds (8*MDW+5) up to 8px.
  Use 9525 EMU/pixel; endpoint offsets stay within cells.
  Allow only exact creationId/useLocalDpi extension structures, preserving bytes. Missing fillRect protects the image.
  Saved xfrm/ext, when present, must exactly match resolved dimensions; never use it alone to guess size.
  Replace image parts only; every other ZIP member must match decompressed bytes exactly, including XML settings.
  Unsupported placements protect that image part across all its references; other independent safe parts may shrink.
  Signed/encrypted/macro/in-cell/richdata/embedded-object workbooks and package-level preflight excess protect
  the whole workbook with an exact original copy. Structure/I/O/runtime failures
  are ERROR without recovery copying; retain existing outputs. Adopt only a validated strictly smaller workbook.
  Excel uses one worker, no state DB/cache, `<output>.excel-report[.dry-run].csv` and `<output>.excel-work/`.
  Dry-run produces only eligibility reports, no completed workbook/candidates, and records zero changed images.
  Limits: ZIP 128 MiB, 4096 entries, central directory 4 MiB checked before ZipFile allocation,
  64 MiB/expanded part, 256 MiB expanded total, 8 MiB/XML, cumulative XML 32 MiB/1M nodes, 1000 images,
  32 MP/image, 200 MP cumulative source/candidate decode and a 300-second cooperative deadline.
  Preflight excess protects; runtime excess is ERROR. Never claim Excel render/print or real-data Pilot validation
  without separate evidence. Unknown image reference owners/extensions protect their referenced image parts.
  ZIP64, multi-disk, and nonstandard central-directory layouts protect the whole workbook.
  CSV schema 3, recipe grid2-pixel-jpeg-v2; images_total is nullable, never confuse unknown with zero.
  Record max_side/dpi exclusively (unused is blank), plus jpeg_quality. Root binds each to the request.
  Same-size changed parts are permitted only for JPEG in pixel mode; root verifies exact cap dimensions.
  Record analysis_complete, diagnostics_complete, image_diagnostics (1000 records, depth8, 2MiB UTF-8/field).
  Child/root finite CSV limits match; root independently checks known inventory with Content Types.
- Standard image recipe: long side `1280`, short side `960`, quality `72`; compact image recipe:
  long side `1024`, short side `768`, quality `60`. Both use JPEG `4:2:0`, white alpha,
  EXIF Orientation applied, no upscale or crop.
- Root and PDF CLI accept a single PDF directly, without staging or neighboring-file discovery.
  Single-PDF default output is `<source-parent>/<source-stem>_軽量化/files/<source-name>`;
  reports/state/preview use the files parent. Explicit output and directory input retain their existing layout.
  Single-PDF root runs only the PDF child. Preserve source identity, path guards and atomic publication.
- Default PDF policy allows confirmed text and image-only scans in both presets. Blank pages may coexist.
  Image-only means no text paint or hidden OCR and no vector paint; clipping paths are allowed.
  Photo-only PDFs also qualify; never claim semantic scan/photo detection.
  Raster scans use 300 DPI gray JPEG quality92, pixel-aligned page placement, preserving page boxes/rotation,
  links, bookmarks and metadata. Existing text/mixed PDFs and explicit policy profiles keep their behavior.
  Preserve overrides automatic processing; standalone safe disables it. Other document-level protection remains.
  classification=raster_scan, permission_basis=automatic_scan_raster, requested_policy/profile=standard or compact.
  Compare independent qpdf and raster_scan candidates; only strictly smaller validated output is adopted, qpdf wins ties.
  raster_scan adoption is ADOPTED_LOSSY; images_changed is selected rasterized page count. Dry-run generates no candidates.
  Limits:100 pages,128MiB input,80MP/source image,32MP/page render,600MP raster generation+validation,
  separate600MP qpdf validation, shared300-second cooperative deadline. Preflight excess protects; runtime excess rejects.
  Full-page300DPI validation: qpdf RGB exact, raster gray mean absolute difference <=5/255 per page and <=10/255 per32x32 tile.
  Source and candidate boxes/rotation/text/links/toc/names/metadata must agree. Raster recipev3 participates in config hash;
  keep schema6 fields and old DB rows. JPEG-lossless request is recorded but adds no candidates to this classification.
  Page rendering can resample low-DPI source images upward; do not claim increased original detail.
  Unselected mixed-text/image PDFs and vector drawings remain protected.
  Root `--pdf-preserve-pattern`, `--pdf-text-pattern`, `--pdf-text-scan-pattern` use the photo glob rules;
  standalone removes `pdf-`. Preserve overrides every permission; other overlapping permissions fail preflight.
  Text patterns allow only text and horizontal/vertical strokes/rectangles. Scan patterns allow simple RGB/Gray
  images; masks, complex Decode/colorspaces, inline or ambiguous placements protect the entire document.
  Structure inspection failures are ERROR with recovery copying, never unsupported guesses.
- Text candidates independently use qpdf, font subset/cleanup plus qpdf, grayscale plus cleanup/qpdf.
  Scan candidates use 300 DPI gray JPEG quality 92/85/80 plus qpdf, and retain a qpdf-only candidate.
  Explicit root `--pdf-text-scan-bilevel-pattern` / PDF `--text-scan-bilevel-pattern` adds an independent
  1-bit DeviceGray/Flate candidate (gray samples below 220 black, otherwise white; no dithering or glyph
  matching). It shares scan protection, DPI, validation and budget limits. Colors/tones are lost; never
  infer this permission automatically. Same-size ties prefer qpdf, JPEG 92/85/80, then bilevel.
  Profile/requested_policy is text_scan_bilevel, classification text_scan, permission_basis
  explicit_text_scan_bilevel; adoption is ADOPTED_LOSSY with kind text_scan_bilevel. Safe rejects it;
  preserve overrides it and other overlapping permissions fail preflight. Hash its patterns and recipe.
  Scan stream Length supports direct and indirect integers; check limits before decoding.
  Preserve text/OCR and geometry; never rasterize text, add OCR, scrub or upscale. These existing profiles
  never substitute fonts; only the explicit font_replace profile below permits substitution.
  Shared images use minimum placement DPI per axis with ceil dimensions. Limits: 100 pages, 80 MP/image,
  64 MiB compressed stream, 600 MP cumulative validation (both renders), 300 seconds cooperative candidate budget.
  Preflight limit excess protects; runtime budget excess rejects the candidate.
  Text validation checks text positions, paths/placements, links/bookmarks/metadata and exact 72/300 DPI
  RGB or source-gray renders. Scan comparison keeps global 5% and local 20% thresholds.
  Text recipes skip neither small PDFs nor small savings: adopt only strictly smaller validated candidates.
  Ties prefer qpdf, color-preserving subset, gray; scan JPEG ties prefer higher quality. Gray is ADOPTED_LOSSY.
  Safe disables grayscale and rejects scan/photo permissions. Preserve never generates any candidates.
- Explicit photo selection uses root `--pdf-photo-pattern` / PDF `--photo-pattern`, repeatable input-relative
  globs. Match case-insensitively, normalize separators, allow `*` across directories, reject empty/absolute/`..`
  patterns, and reject photo selection with PDF `--safe`. Do not infer photo content or OCR need from DPI.
- Selected PDFs use `photo` profile: only simple 8-bit DeviceRGB/DeviceGray DCT JPEGs, quality `80`, and
  root `--pdf-photo-dpi` / PDF `--photo-dpi` integer `150` to `300`, default `200`. Explicit DPI requires
  photo patterns and does not change the text-scan `300` DPI target.
  Preserve non-JPEG, 1-bit, masks, complex color/Decode transforms, and ambiguous image-reference
  groups. Photo placement inspection failures are `ERROR`. Use the minimum placement
  DPI per shared-xref axis and ceil pixel dimensions; keep axes at or below the target DPI unchanged and do not
  recompress when neither dimension shrinks. Never upscale or rebuild PDF through HTML.
- Optional root `--pdf-preview` / PDF `--preview` defaults OFF and covers all PDF results, including preservation reasons. The PDF processor
  creates static local HTML/JS and PNGs comparing originals with actual completed outputs at matched scale.
  Repeated `--pdf-preview-dpi` / `--preview-dpi` accepts 150 to 300, at most five distinct values, deduplicated
  in descending order. Generate those comparison-only candidates only for unprotected photo PDFs, independently from the original;
  they never change normal candidate selection or successful processing state.
  Bundle copied original/output/candidate PDFs and images under `<output-parent>/pdf-preview/<runid>/`.
  Keep the entire run directory for portable viewing; no server or CDN is required.
  Preview limits per PDF: 100 pages, 500 image regions, 32 MP per render, 600 MP cumulative, 300 seconds
  cooperative budget. Render whole pages at 144 DPI and image regions at 300 DPI RGB. Preview failures
  remain separate ERRORs with exit 1, preserve completed PDF results, and continue independent files.
  Write `pdf-preview.json` or `pdf-preview.dry-run.json` in the output parent. Dry-run writes requests only,
  with no HTML, PNG, comparison PDF, or additional external-tool execution.
- Font replacement itself is opt-in; ordinary PDF compression never replaces fonts. Meiryo is the default replacement font, not automatic permission to replace.
- Explicit root `--pdf-font-replace-pattern` / PDF `--font-replace-pattern` selects font_replace only.
  Use the same relative-glob rules, preserve priority and conflicting-permission preflight as other PDF policies.
  PDF `--safe` rejects it. Use installed Windows meiryo.ttc face 0, Meiryo Regular by default; explicit root --pdf-font-family yu-gothic / PDF --font-family yu-gothic selects YuGothR.ttc face 0, Yu Gothic Regular. Require font-replace patterns for explicit family, bind family to hash/report/preview/root validation, and retain font SHA checks. For supported horizontal
  Japanese/English text; verify family/style, embedding flags and the whole font file SHA-256. Never bundle,
  download or modify Windows font outlines/metrics. Subset mapped Unicode (including unused source mappings);
  adjust widths/spacing on the PDF side. Preserve orthogonal rotated horizontal text; protect vertical writing,
  nonorthogonal, reflected or degenerate text matrices. Preserve bounded passive BMC/BDC/EMC only; reject
  ActualText, OC and resource-property indirection, and validate inline property types with depth at most 64.
  Never add ActualText or replace image-burned text. Missing glyphs and unsupported encoding/structures protect
  the entire document; structure, tool and I/O failures remain ERROR even with successful recovery copying.
  Compare independently validated original-derived qpdf-only and font_replace+qpdf candidates; adopt only
  strictly smaller output, prefer qpdf on ties. Font substitution adoption is ADOPTED_LOSSY. lossless_jpeg
  still records the request but adds no candidates in this profile. Dry-run reads fonts/structure only.
  No selected font_replace files after preserve resolution means no Windows font preparation is required.
  Validate displayed text/order/origins and non-text content independently. Copy/search inferred whitespace
  may change; text_extraction_changed reports MuPDF extraction differences, never all-viewer equivalence.
  Font limits: 200 pages, 128 MiB source, 256 fonts, 1,000,000 text-show characters and 1,000,000 total
  source character mappings across fonts. Preflight validates unused ExtGState definitions too. Source font/image streams
  32 MiB compressed and 64 MiB decoded each; source content 32 MiB compressed/decoded and 32 MiB document
  decoded-content total; source decoded-stream total 256 MiB. Candidate validation caps each stream at 32 MiB compressed/64 MiB decoded
  and both PDFs' decoded streams at 256 MiB; images/renders 32 MP each. Render both PDFs at 144 DPI,
  600 MP per candidate, at most two candidates (1,200 MP). Share a 300-second cooperative deadline across
  preflight and candidates. Preflight excess protects; runtime excess rejects the candidate. Origins allow
  0.02 pt per coordinate; qpdf-only requires exact rendered pixels, font replacement allows changed glyphs.
  Font previews retain the independent 100-page limit and recheck processing metadata plus original/output
  SHA instead of applying the ordinary text classifier. Root preview items require the font request/name/
  extraction-change fields to match the validated PDF report with strict boolean types.
- PDF processing schema is `6`; record requested_policy, classification, permission_basis, preservation_reason; include `photo_dpi` in the processing hash and retain old DB rows through
  additive migration. CSV/DB `photo_dpi` is the requested integer for photo rows and empty/NULL otherwise;
  root rejects missing or mismatched values. Preview options are excluded from the processing hash.
  Add font_replacement_requested, replacement_font, replacement_font_sha256, text_extraction_changed to CSV/DB
  through additive migration. Only font_replace rows request true and record the requested Yu Gothic Regular or Meiryo Regular plus lowercase
  64-hex font-file SHA; all other profiles record false/empty/empty. Preserve/dry-run/qpdf wins retain requests.
  text_extraction_changed is true only for an adopted font_replace lossy candidate with extraction differences;
  otherwise false. Root requires all fields, profile agreement and identical font SHA across the run's font rows.
  Font recipe, installed-font SHA and fontTools/pikepdf versions participate in config hashes; schema 5
  successes must run again.
- Photo candidates add bounded 300 DPI changed-placement validation; this does not guarantee readability
  or OCR accuracy. Photo lossy adoption requires `64 KiB` and `5%`, photo lossless `16 KiB` and `2%`.
  The below-256-KiB skip applies to photo, not text recipes. PRESERVED_ORIGINAL requires output/source SHA equality;
  DRY_RUN_PRESERVED records protection without completed output. Hash every policy pattern and text recipe.
- Optional root `--pdf-lossless-jpeg` / PDF `--lossless-jpeg` adds baseline/progressive JPEG candidates;
  default OFF, compatible with PDF `--safe`. Manually prepared jpegtran 3.2.0 only, explicit path then PATH;
  path alone does not enable it. No jpegtran download/install code. Dry-run never executes it.
- JPEG optimization preserves simple 8-bit DeviceRGB/DeviceGray single-DCT image dictionaries and dimensions,
  DQT/components and decoded pixels. Masks, Decode/DecodeParms, complex colors and inline images are excluded.
  Limits: 20 MP, 32 MiB stream, 128M tool memory, 100 input scans, 30 seconds/call, 300 seconds/document
  cooperative JPEG budget. Exact geometry/text/paths and full-page tiled RGB at 72/300 DPI are checked.
  Pixel/render mismatch and budget exhaustion reject that candidate; tool/structure/I/O failures remain ERROR.
- Candidate size ties prefer qpdf, JPEG baseline, JPEG progressive, then lossy. JPEG adoption uses
  ADOPTED_LOSSLESS; history kinds are jpeg_lossless_baseline/jpeg_lossless_progressive. All PDF CSV rows
  include lossless_jpeg_requested as true/false; root rejects missing or mismatched values.
- For lossy processing, also create a lossless candidate from the original; select the smallest validated
  candidate meeting its reduction gates, preferring lossless on a size tie. Real tool, structure, and I/O
  failures remain `ERROR`, including when recovery copying succeeds. Retain primary-candidate
  diagnostics and full `candidate_details` in state/CSV; root verifies each required report `profile`.
- Compact video: simple SDR streams are encoded without upscale to at most `1280x720`, at most
  `30 fps`, using SVT-AV1. Default allows missing progressive/SAR metadata and converts VFR to CFR.
  Root `--video-safe` / standalone `--safe` restores explicit progressive/SAR 1:1/CFR input checks.
  Known HDR/interlace/non-square SAR, subtitles, multiple video streams remain unsupported.
  Root `--video-remove-audio` / standalone `--remove-audio` removes all audio while compressing;
  multiple/multichannel audio is accepted for removal. Both flags default OFF and require compact.
  Removal failures including unsupported/quality/savings rejection are ERROR with no audible fallback
  or recovery copy; existing outputs are retained. Other unsupported/complex videos are copied unchanged.
  CSV safe/remove_audio booleans must match the root request; both enter the v2 processing hash.
- Video candidates must pass stream/duration checks, full decode, VMAF, and size-reduction gates.
  Tool/encoding failures remain `ERROR` even if a recovery copy succeeds; do not silently count them as skips.
- Image metadata is best-effort, not a sanitization guarantee.
- Root dry-run creates no completed PDF/image/video outputs but may update PDF state and reports. Video
  dry-run may initialize an empty state workspace but does not read or overwrite successful normal records.
- PDF uses `<output-parent>/report.csv`, `<output-parent>/report.dry-run.csv`, and
  `<output-parent>/.pdf-shrink/` for state/temp. Image errors use `<output>.image-errors.csv`;
  all image results use `<output>.image-manifest.csv` or `<output>.image-manifest.dry-run.csv`.
- Video reports use `<output>.video-report[.dry-run].csv`; state/temp use `<output>.video-state/`.

## Documentation rules

- Keep end-user procedures and safety information in `MANUAL.md`.
- Keep `README.md` short and route users to the manual.
- Keep component README files limited to component-specific CLI and contracts.
- Preserve exact numbers, commands, names, status values, paths, causality, and known uncertainty.
- State unresolved contradictions; do not fill them with assumptions.
- Update every affected document when behavior changes.
- Update architecture JSON with the `archify` skill when runtime boundaries or paths change.
- The architecture source is `docs/architecture/karufile-runtime.architecture.json`; README currently
  links to `docs/architecture/karufile-runtime.compact.html` and its matching visual-check artifacts.
  Do not overwrite the older `karufile-runtime.html` merely to match the source filename.
- Never hand-edit the generated architecture HTML. Validate, deliver, run `visual-check`, and inspect its
  light/dark screenshots. Keep the repository revision and source evidence exact.

## Work status and scope

- Read `.agent/execplans/README.md` before resuming multi-stage work. It currently lists compact work as
  interrupted, with `2026-09-04-compact-preset.md` and `2026-09-04-compact-preset-handoff.md` as the plan
  and handoff. Recheck described issues against current code; these records are not current test results.
- Do not infer completion from the presence of compact code or documentation. Resolve remaining work
  and run the relevant verification before changing a plan's completion status.
- Preserve unrelated working-tree changes and untracked work. Updating instructions or ignore rules
  does not authorize fixing other implementation issues or committing/publishing changes.

## Validation

For runtime changes, run the affected suites and compilation checks below; use the full set for
cross-component changes or final implementation verification. For documentation or ignore-only edits,
check referenced paths/commands or ignore behavior and run `git diff --check`; runtime suites are not
required unless executable behavior changes. Report exactly what was run.

Run from the repository root (the orchestrator suite requires its own working directory):

```powershell
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
uv run --project excel-shrink python -m pytest -q excel-shrink/tests
uv run --project video-shrink python -m pytest -q video-shrink/tests
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project excel-shrink python -m compileall -q excel-shrink/src excel-shrink/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --script karufile.py --help
git diff --check
```

The automated tests use small synthetic fixtures. Do not report a real-data Pilot as completed without
separate evidence.
