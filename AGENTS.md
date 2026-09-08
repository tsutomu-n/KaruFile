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
- `orchestrator/shrink_all.py`: validates paths and input/output identities, runs PDF then images,
  and runs video only for `compact`. Validates reports/manifests against current inputs and outputs
  before combining results; do not replace this with stdout parsing or approximate counts.
- `pdf-shrink/`: only PDF processor; owns PDF state and reports.
- `media-shrink-tool/`: only standalone-image processor; outputs JPEG and owns image error reports/manifests.
- `video-shrink/`: only standalone-video processor; owns video state and reports and calls external FFmpeg tools.

Do not move PDF or video processing into `media-shrink-tool`. HDR/VFR/interlaced/complex-stream video
conversion, deduplication, perceptual hashing, source deletion, and a GUI are outside the supported scope.

The root CLI's `standard` preset does not discover or copy videos. The standalone video CLI's
`standard` preset copies discovered videos without transcoding; preserve this distinction.

## Development layout

- Run repository commands from the root unless a command explicitly changes directory.
- Each processor has its own `pyproject.toml`, `uv.lock`, and local `.venv`; there is no root Python project.
  The root entry point uses inline script metadata; the orchestrator uses the standard library.
- Root/PDF/video require Python 3.13 or later; the image component declares Python 3.11 or later.
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
- Standard image recipe: long side `1280`, short side `960`, quality `72`; compact image recipe:
  long side `1024`, short side `768`, quality `60`. Both use JPEG `4:2:0`, white alpha,
  EXIF Orientation applied, no upscale or crop.
- PDF placed images: standard/compact use a fixed `300` DPI candidate target from each placement transform axis,
  never upscale, keep vector text, and retain the original when candidate validation rejects it.
  Do not use JPEG xres/yres. 1-bit and soft-mask images are left unchanged.
- PDF JPEG candidate quality is `92` for standard and `80` for compact. Compact also permits
  same-dimension JPEG recompression; it does not lower the fixed DPI target.
- Explicit photo selection uses root `--pdf-photo-pattern` / PDF `--photo-pattern`, repeatable input-relative
  globs. Match case-insensitively, normalize separators, allow `*` across directories, reject empty/absolute/`..`
  patterns, and reject photo selection with PDF `--safe`. Do not infer photo content or OCR need from DPI.
- Selected PDFs use `photo` profile: only simple 8-bit DeviceRGB/DeviceGray DCT JPEGs, quality `80`, and
  root `--pdf-photo-dpi` / PDF `--photo-dpi` integer `150` to `300`, default `200`. Explicit DPI requires
  photo patterns and does not change the standard/compact `300` DPI target.
  Preserve non-JPEG, 1-bit, masks, complex color/Decode transforms, and ambiguous image-reference
  groups. Photo placement inspection failures are `ERROR`. Use the minimum placement
  DPI per shared-xref axis and ceil pixel dimensions; keep axes at or below the target DPI unchanged and do not
  recompress when neither dimension shrinks. Never upscale or rebuild PDF through HTML.
- Optional root `--pdf-preview` / PDF `--preview` requires photo patterns and defaults OFF. The PDF processor
  creates static local HTML/JS and PNGs comparing originals with actual completed outputs at matched scale.
  Repeated `--pdf-preview-dpi` / `--preview-dpi` accepts 150 to 300, at most five distinct values, deduplicated
  in descending order. Generate those comparison-only candidates independently from the original;
  they never change normal candidate selection or successful processing state.
  Bundle copied original/output/candidate PDFs and images under `<output-parent>/pdf-preview/<runid>/`.
  Keep the entire run directory for portable viewing; no server or CDN is required.
  Preview limits per PDF: 100 pages, 500 image regions, 32 MP per render, 600 MP cumulative, 300 seconds
  cooperative budget. Render whole pages at 144 DPI and image regions at 300 DPI RGB. Preview failures
  remain separate ERRORs with exit 1, preserve completed PDF results, and continue independent files.
  Write `pdf-preview.json` or `pdf-preview.dry-run.json` in the output parent. Dry-run writes requests only,
  with no HTML, PNG, comparison PDF, or additional external-tool execution.
- PDF processing schema is `4`; include `photo_dpi` in the processing hash and retain old DB rows through
  additive migration. CSV/DB `photo_dpi` is the requested integer for photo rows and empty/NULL otherwise;
  root rejects missing or mismatched values. Preview options are excluded from the processing hash.
- Photo candidates add bounded 300 DPI changed-placement validation; this does not guarantee readability
  or OCR accuracy. Photo lossy adoption requires `64 KiB` and `5%`; other lossy candidates require `256 KiB`
  and `5%`, lossless candidates `16 KiB` and `2%`. The below-256-KiB PDF skip remains in every profile.
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
- Compact video: only supported simple SDR/CFR streams are encoded without upscale to at most
  `1280x720`, at most `30 fps`, using SVT-AV1. Unsupported/complex videos are copied unchanged.
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
uv run --project video-shrink python -m pytest -q video-shrink/tests
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project video-shrink python -m compileall -q video-shrink/src video-shrink/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --script karufile.py --help
git diff --check
```

The automated tests use small synthetic fixtures. Do not report a real-data Pilot as completed without
separate evidence.
