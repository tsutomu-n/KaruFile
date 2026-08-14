"""設定ファイル読み込みとデフォルト値。"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def default_config() -> dict[str, Any]:
    return {
        "input_dir": ".",
        "output_dir": "{input_dir}_resized",
        "dry_run": False,
        "trash": True,
        "workers": 4,
        "image": {
            "max_width": 1200,
            "quality": 85,
            "format": "jpg",
            "skip_if_smaller": True,
            "preserve_exif": True,
            "preserve_icc": True,
        },
        "video": {
            "codec": "libx264",
            "crf": 23,
            "preset": "medium",
            "max_height": 1080,
            "audio_codec": "aac",
            "audio_bitrate": "128k",
        },
        "pdf": {
            "mode": "lossless",  # lossless | lossy
            "dpi": 150,
            "text_threshold": 100,
        },
        "dedup": {
            "min_size": 1024,
            "perceptual": False,
            "hash_threshold": 5,
        },
    }


def load_config(path: Path | None = None, input_dir: Path | None = None) -> dict[str, Any]:
    cfg = default_config()
    if path and path.exists():
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with path.open("rb") as f:
            user_cfg = tomllib.load(f)
        cfg = _merge(cfg, user_cfg)

    if input_dir:
        cfg["input_dir"] = str(input_dir)

    # output_dir の {input_dir} プレースホルダを展開
    cfg["output_dir"] = cfg["output_dir"].format(input_dir=cfg["input_dir"])
    return cfg


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def get_output_dir(cfg: dict[str, Any]) -> Path:
    return Path(cfg["output_dir"])
