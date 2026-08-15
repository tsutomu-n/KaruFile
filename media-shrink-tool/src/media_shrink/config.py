"""KaruFile v1 の固定画像レシピ。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


RECIPE_LINES = (
    "max_long=1280",
    "max_short=960",
    "quality=72",
    "subsampling=4:2:0",
    "alpha=white",
    "orientation=apply",
)
RECIPE_HASH = hashlib.sha256("\n".join(RECIPE_LINES).encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class ImageConfig:
    """出力品質に関わる値は製品契約として固定する。"""

    workers: int = 4
    dry_run: bool = False
    max_long: int = field(default=1280, init=False)
    max_short: int = field(default=960, init=False)
    quality: int = field(default=72, init=False)
    subsampling: int = field(default=2, init=False)  # Pillow の 2 は JPEG 4:2:0。
    optimize: bool = field(default=True, init=False)
    progressive: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be at least 1")

    @property
    def recipe_hash(self) -> str:
        return RECIPE_HASH


def default_output_dir(input_dir: Path) -> Path:
    """個別 CLI の既存既定値 ``<input>_resized`` を維持する。"""

    return Path(f"{input_dir}_resized")
