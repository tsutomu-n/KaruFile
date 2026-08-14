"""qpdf の自動取得とラッパー。"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from .config import QpdfOptions
from .utils import ensure_dir, logger

DEFAULT_QPDF_VERSION = "12.3.2"


def _cache_dir(version: str) -> Path:
    local_appdata = Path.home() / "AppData" / "Local"
    if "LOCALAPPDATA" in os.environ:
        local_appdata = Path(os.environ["LOCALAPPDATA"])
    return local_appdata / "pdf-shrink" / "qpdf" / version


def _find_qpdf_exe(root: Path) -> Path | None:
    for path in root.rglob("qpdf.exe"):
        if path.is_file():
            return path
    return None


def _is_executable(path: Path) -> bool:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        return result.returncode == 0 and b"qpdf" in (result.stdout or b"")
    except Exception:
        return False


def ensure_qpdf(
    qpdf_path: str | Path | None = None,
    version: str = DEFAULT_QPDF_VERSION,
) -> Path:
    """qpdf.exe を探し、見つからなければ自動取得する。"""
    if qpdf_path:
        exe = Path(qpdf_path).expanduser().resolve()
        if not exe.is_file():
            raise RuntimeError(f"--qpdf-path is not a file: {exe}")
        if not _is_executable(exe):
            raise RuntimeError(f"--qpdf-path is not an executable qpdf: {exe}")
        return exe

    # 1. PATH 上の qpdf
    for name in ("qpdf", "qpdf.exe"):
        found = shutil.which(name)
        if found:
            exe = Path(found)
            if _is_executable(exe):
                logger.info("Using qpdf from PATH: %s", exe)
                return exe

    # 2. キャッシュ
    cache = _cache_dir(version)
    cached = _find_qpdf_exe(cache)
    if cached and _is_executable(cached):
        logger.info("Using cached qpdf: %s", cached)
        return cached

    # 3. 自動ダウンロード
    return _download_qpdf(version, cache)


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in archive.infolist():
        target = (root / member.filename).resolve()
        if not target.is_relative_to(root):
            raise RuntimeError(f"Unsafe path in qpdf archive: {member.filename}")
    archive.extractall(root)


def _download_qpdf(version: str, cache: Path) -> Path:
    url = f"https://github.com/qpdf/qpdf/releases/download/v{version}/qpdf-{version}-msvc64.zip"
    zip_name = f"qpdf-{version}-msvc64.zip"
    zip_path = cache / zip_name

    logger.info("Downloading qpdf %s from %s", version, url)
    ensure_dir(cache)
    try:
        urllib.request.urlretrieve(url, zip_path)
    except Exception as exc:
        raise RuntimeError(
            f"Failed to download qpdf from {url}. "
            "Please download qpdf manually and use --qpdf-path."
        ) from exc

    logger.info("Extracting qpdf to %s", cache)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract(zf, tmp_path)
        found = _find_qpdf_exe(tmp_path)
        if not found:
            raise RuntimeError(f"qpdf.exe not found in downloaded archive: {zip_path}")

        # bin ディレクトリまでコピーして構成を安定させる
        bin_dir = cache / "bin"
        ensure_dir(bin_dir)
        for dep in found.parent.iterdir():
            if dep.is_file():
                shutil.copy2(dep, bin_dir / dep.name)
        exe = bin_dir / "qpdf.exe"

    if not _is_executable(exe):
        raise RuntimeError(f"Downloaded qpdf is not executable: {exe}")
    logger.info("qpdf ready: %s", exe)
    return exe


def qpdf_version(exe: Path) -> str:
    result = subprocess.run(
        [str(exe), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    first = (result.stdout or "").strip().splitlines()[0] if result.stdout else ""
    return first.strip()


def qpdf_check(exe: Path, path: Path) -> int:
    """qpdf --check を実行し、終了コードを返す。"""
    result = subprocess.run(
        [str(exe), "--check", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=300,
    )
    return result.returncode


def qpdf_optimize(
    exe: Path,
    src: Path,
    dst: Path,
    options: QpdfOptions,
) -> None:
    """qpdf による可逆最適化を実行する。"""
    cmd = [str(exe)]
    cmd.append(f"--compress-streams={options.compress_streams}")
    cmd.append(f"--decode-level={options.decode_level}")
    if options.recompress_flate:
        cmd.append("--recompress-flate")
    cmd.append(f"--compression-level={options.compression_level}")
    cmd.append(f"--object-streams={options.object_streams}")
    cmd.extend([str(src), str(dst)])

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=300,
    )
    # 終了コード3は警告のみ。処理後の検証（qpdf --check）で詳細を判定する。
    if result.returncode == 2 or result.returncode not in (0, 3):
        err = result.stderr[-500:] if result.stderr else ""
        raise RuntimeError(f"qpdf optimize failed (rc={result.returncode}): {err}")
