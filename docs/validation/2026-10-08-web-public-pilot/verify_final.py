"""このPilotの文書参照、生成物SHA、baselineとの変更境界をローカルで照合する。"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit
import unicodedata
import zipfile


ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
BASE_HEAD = "79df924a924808b4aa7601d7aa797d15ecfd4dcc"
ALLOWED = {
    ".agent/execplans/README.md", "AGENTS.md", "MANUAL.md", "docs/README.md",
    "docs/REFERENCE.md", "docs/WEB_PUBLIC.md",
    "media-shrink-tool/src/media_shrink/image.py",
    "media-shrink-tool/src/media_shrink/web_public.py",
    "media-shrink-tool/src/media_shrink/web_public_batch.py",
    "media-shrink-tool/tests/test_web_public_cli.py",
    *["docs/architecture/" + name for name in (
        "karufile-runtime.architecture.json", "karufile-runtime.compact.delivery.json",
        "karufile-runtime.compact.html", "karufile-runtime.compact.review.md",
        "karufile-runtime.compact.visual-check.1440x900.dark.png",
        "karufile-runtime.compact.visual-check.1440x900.light.png",
        "karufile-runtime.compact.visual-check.2048x1320.dark.png",
        "karufile-runtime.compact.visual-check.2048x1320.light.png",
        "karufile-runtime.compact.visual-check.json", "karufile-runtime.compact.worktree.json",
    )],
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, encoding="utf-8", capture_output=True)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result.stdout


def heading_ids(path):
    text = re.sub(r"```[^\n]*\n.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
    counts = {}
    ids = set(re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', text))
    for heading in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", text, re.M):
        value = "".join(character for character in heading.lower()
                        if unicodedata.category(character)[0] not in "PS" or character in "-_").replace(" ", "-")
        index = counts.get(value, 0)
        counts[value] = index + 1
        ids.add(value if index == 0 else f"{value}-{index}")
    return ids


def main():
    captured = datetime.now(timezone(timedelta(hours=9))).isoformat()
    baseline = read_json(EVIDENCE / "baseline-source-sha256.json")
    assert baseline["head"] == git("rev-parse", "HEAD").strip() == BASE_HEAD
    assert baseline["branch"] == git("branch", "--show-current").strip() == "main"
    git("diff", "--cached", "--exit-code")
    diff = subprocess.run(["git", "diff", "--check"], cwd=ROOT, encoding="utf-8", capture_output=True)
    assert diff.returncode == 0, diff.stdout + diff.stderr
    changed = []
    for relative, before in sorted(baseline["tracked_sha256"].items()):
        path = ROOT / relative
        assert path.is_file(), f"Tracked file missing: {relative}"
        after = sha(path)
        if before != after:
            assert relative in ALLOWED, f"Unexpected tracked change: {relative}"
            changed.append({"path": relative, "before_sha256": before, "after_sha256": after})
    assert {row["path"] for row in changed} == set(git("diff", "--name-only").splitlines())
    zip_path = ROOT / "KaruFile_Codex_Pilot_20261008.zip"
    assert sha(zip_path) == "008d8d9f2dd3229a3bff1b755dd0585e04c7070a2becf7eeb9d6271fe1bcc341"
    with zipfile.ZipFile(zip_path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        for item in members:
            assert (ROOT / item.filename).read_bytes() == archive.read(item)

    snapshot = read_json(ROOT / "docs/architecture/karufile-runtime.compact.worktree.json")
    assert snapshot["base_revision"] == BASE_HEAD
    for item in snapshot["files"]:
        assert sha(ROOT / item["path"]) == item["sha256"], item["path"]
    spec_sha = sha(ROOT / "docs/architecture/karufile-runtime.architecture.json")
    html_sha = sha(ROOT / "docs/architecture/karufile-runtime.compact.html")
    delivery = read_json(ROOT / "docs/architecture/karufile-runtime.compact.delivery.json")
    visual = read_json(ROOT / "docs/architecture/karufile-runtime.compact.visual-check.json")
    assert spec_sha == snapshot["specification_sha256"] == delivery["specification"]["sha256"]
    assert html_sha == snapshot["artifact_sha256"] == delivery["artifact"]["sha256"] == visual["artifact"]["sha256"]
    assert delivery["ok"] and visual["ok"] and delivery["validation"]["errors"] == 0
    assert all(item["ok"] for item in visual["containment"]["viewports"])

    documents = [ROOT / name for name in (
        "AGENTS.md", "MANUAL.md", "docs/README.md", "docs/REFERENCE.md", "docs/WEB_PUBLIC.md",
        ".agent/execplans/README.md", ".agent/execplans/2026-10-08-web-public-pilot.md",
        "docs/architecture/karufile-runtime.compact.review.md",
    )] + list(EVIDENCE.glob("*.md"))
    checked_paths = 0
    checked_anchors = 0
    pending_receipts = {EVIDENCE / "static-checks.json", EVIDENCE / "final-boundary.json"}
    for document in documents:
        for raw in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", document.read_text(encoding="utf-8")):
            target = raw.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith("//"):
                continue
            path = (document.parent / unquote(parsed.path)).resolve() if parsed.path else document
            assert path.exists() or path in pending_receipts, (document, target)
            checked_paths += 1
            if parsed.fragment and path.suffix == ".md":
                assert unquote(parsed.fragment) in heading_ids(path), (document, target)
                checked_anchors += 1

    for name in ("image", "pdf", "excel", "video", "orchestrator"):
        assert read_json(EVIDENCE / f"final-{name}.json")["exit_code"] == 0
    for name in ("image", "pdf", "excel", "video"):
        assert read_json(EVIDENCE / f"compile-{name}.json")["exit_code"] == 0
    assert all(item["exit_code"] == 0 for item in read_json(EVIDENCE / "final-checks.json"))
    assert read_json(EVIDENCE / "baseline-synthetic.json") == read_json(EVIDENCE / "final-synthetic.json")
    for name in ("web-public", "resize"):
        assert (EVIDENCE / f"baseline-{name}-help.utf8.txt").read_bytes() == (EVIDENCE / f"final-{name}-help.txt").read_bytes()
    ast.parse((ROOT / "media-shrink-tool/src/media_shrink/file_identity.py").read_text(encoding="utf-8"), feature_version=(3, 11))

    checks = {
        "captured_jst": captured, "exit_code": 0, "git_diff_check_exit": diff.returncode,
        "markdown_files": len(documents), "local_paths_checked": checked_paths,
        "markdown_anchors_checked": checked_anchors, "architecture_sources_checked": len(snapshot["files"]),
        "architecture_sha_match": True, "full_suite_receipts_exit_zero": True,
        "comparison_equal": True, "cli_help_equal": True, "python_3_11_syntax": True,
        "python_3_11_runtime": "NOT_RUN", "zip_members_unchanged": len(members),
    }
    write_json(EVIDENCE / "static-checks.json", checks)
    new = set(filter(None, git("ls-files", "--others", "--exclude-standard", "-z").split("\0")))
    new.add((EVIDENCE / "final-boundary.json").relative_to(ROOT).as_posix())
    allowed_new = {"KaruFile_Codex_Pilot_20261008.zip", ".agent/execplans/2026-10-08-web-public-pilot.md",
                   "media-shrink-tool/src/media_shrink/file_identity.py", "media-shrink-tool/tests/test_file_identity.py"}
    for name in new:
        assert name in allowed_new or name.startswith(("KaruFile_Codex_Pilot_20261008/", "docs/validation/2026-10-08-web-public-pilot/")), name
    boundary = {
        "captured_jst": captured, "branch": "main", "start_head": BASE_HEAD, "end_head": BASE_HEAD,
        "baseline_tracked_files": len(baseline["tracked_sha256"]), "modified_files": changed,
        "unchanged_tracked_files": len(baseline["tracked_sha256"]) - len(changed),
        "new_files": sorted(new), "unexpected_changes": [], "staged_changes": False,
        "original_zip_sha256": sha(zip_path), "zip_members_unchanged": len(members),
        "protected_components_and_locks_unchanged": True,
        "commit": "NOT_RUN", "push": "NOT_RUN", "pr": "NOT_RUN", "production_publish": "NOT_RUN",
    }
    write_json(EVIDENCE / "final-boundary.json", boundary)
    print(json.dumps({**checks, "modified_files": len(changed), "new_files": len(new)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
