# KaruFile repository instructions

## Sources of truth

1. Executable behavior: code, tests, project configuration, and lockfiles.
2. Exact product contracts: `docs/REFERENCE.md`.
3. End-user procedures and safety: `MANUAL.md`.
4. Documentation roles and history: `docs/README.md`.

When documentation conflicts with executable behavior, verify the code and tests, then update every affected
document in the same change. Do not invent setup, behavior, guarantees, or validation results.

## Architecture

- `karufile.py`: normal user entry point; requires Python 3.13 or later.
- `orchestrator/shrink_all.py`: validates paths, runs PDF then image processing, and combines results.
- `pdf-shrink/`: only PDF processor; owns PDF state and reports.
- `media-shrink-tool/`: only standalone-image processor; outputs JPEG.

Do not move PDF processing into `media-shrink-tool`. Video compression, deduplication, perceptual hashing,
source deletion, and a GUI are outside KaruFile v1.

## Required contracts

- Never modify or delete input files.
- Write completed files to a separate output tree while preserving relative directories.
- Reject equal or nested input/output paths and unsafe symlink, junction, or hard-link destinations.
- Publish outputs and reports through validated temporary files and `os.replace()` where implemented.
- Continue independent files after a per-file failure; return nonzero when any required result fails.
- Root defaults: output `<input>_軽量化`, PDF workers `2`, image workers `4`.
- Image recipe: long side `1280`, short side `960`, quality `72`, JPEG `4:2:0`, white alpha,
  EXIF Orientation applied, no upscale or crop.
- PDF placed images: cap effective DPI at `300` from display size, no upscale, keep vector
  text. Do not use JPEG xres/yres. 1-bit and soft-mask images are left unchanged.
- Image metadata is best-effort, not a sanitization guarantee.
- Root dry-run creates no completed PDF/image outputs but may update state and reports.
- PDF report/state paths are based on the output parent. Image errors use `<output>.image-errors.csv`.

## Documentation rules

- Keep end-user procedures and safety information in `MANUAL.md`.
- Keep `README.md` short and route users to the manual.
- Keep component README files limited to component-specific CLI and contracts.
- Preserve exact numbers, commands, names, status values, paths, causality, and known uncertainty.
- State unresolved contradictions; do not fill them with assumptions.
- Update every affected document when behavior changes.
- Update architecture JSON with the `archify` skill when runtime boundaries or paths change.
- Never hand-edit the generated architecture HTML. Validate, deliver, run `visual-check`, and inspect its
  light/dark screenshots. Keep the repository revision and source evidence exact.

## Validation

Run from the repository root:

```powershell
uv run --project pdf-shrink python -m pytest -q pdf-shrink/tests
uv run --project media-shrink-tool --extra dev python -m pytest -q media-shrink-tool/tests
Push-Location orchestrator
uv run --with pytest python -m pytest -q
Pop-Location
uv run --project pdf-shrink python -m compileall -q pdf-shrink/src pdf-shrink/tests
uv run --project media-shrink-tool python -m compileall -q media-shrink-tool/src media-shrink-tool/tests
uv run --project pdf-shrink python -m compileall -q karufile.py orchestrator
uv run --script karufile.py --help
git diff --check
```

The automated tests use small synthetic fixtures. Do not report a real-data Pilot as completed without
separate evidence.
