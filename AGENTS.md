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
- PDF placed images: use a fixed `300` DPI candidate target from each placement transform axis in every preset,
  never upscale, keep vector text, and retain the original when candidate validation rejects it.
  Do not use JPEG xres/yres. 1-bit and soft-mask images are left unchanged.
- PDF JPEG candidate quality is `92` for standard and `80` for compact. Compact also permits
  same-dimension JPEG recompression; it does not lower the fixed DPI target.
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
