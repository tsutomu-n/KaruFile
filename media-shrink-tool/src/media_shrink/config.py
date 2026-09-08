"""KaruFile の画像変換プリセット。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast


ImagePreset = Literal["standard", "compact"]
IMAGE_PRESETS: tuple[ImagePreset, ...] = ("standard", "compact")


@dataclass(frozen=True, slots=True)
class ImageRecipe:
    """画像出力に影響するプリセット値。

    recipe hash入力は旧markerと同じ6項目を維持し、生成済み入力のpresetを識別できる
    ようにする。完成出力の再利用自体はsource SHA-256を持つimage-v2 markerで判定する。
    """

    preset: ImagePreset
    max_long: int
    max_short: int
    quality: int
    subsampling: int = 2  # Pillow の 2 は JPEG 4:2:0。
    optimize: bool = True
    progressive: bool = True
    alpha: str = "white"
    orientation: str = "apply"

    def __post_init__(self) -> None:
        if self.max_long < 1 or self.max_short < 1:
            raise ValueError("image dimension limits must be at least 1")
        if not 1 <= self.quality <= 100:
            raise ValueError("JPEG quality must be between 1 and 100")
        if self.subsampling != 2:
            raise ValueError("only JPEG 4:2:0 subsampling is supported")
        if self.alpha != "white" or self.orientation != "apply":
            raise ValueError("unsupported image recipe contract")

    @property
    def recipe_lines(self) -> tuple[str, ...]:
        return (
            f"max_long={self.max_long}",
            f"max_short={self.max_short}",
            f"quality={self.quality}",
            "subsampling=4:2:0",
            f"alpha={self.alpha}",
            f"orientation={self.orientation}",
        )

    @property
    def recipe_hash(self) -> str:
        return hashlib.sha256("\n".join(self.recipe_lines).encode("ascii")).hexdigest()


STANDARD_RECIPE = ImageRecipe(
    preset="standard",
    max_long=1280,
    max_short=960,
    quality=72,
)
COMPACT_RECIPE = ImageRecipe(
    preset="compact",
    max_long=1024,
    max_short=768,
    quality=60,
)
_RECIPES: dict[ImagePreset, ImageRecipe] = {
    "standard": STANDARD_RECIPE,
    "compact": COMPACT_RECIPE,
}

# 既存のimportとmarker hashの互換性を維持する。
RECIPE_LINES = STANDARD_RECIPE.recipe_lines
RECIPE_HASH = STANDARD_RECIPE.recipe_hash


def image_recipe_for(preset: str) -> ImageRecipe:
    """プリセット名から不変の画像レシピを返す。"""

    if preset not in IMAGE_PRESETS:
        choices = ", ".join(IMAGE_PRESETS)
        raise ValueError(f"unknown image preset {preset!r}; expected one of: {choices}")
    return _RECIPES[cast(ImagePreset, preset)]


def image_preset_for_recipe_hash(recipe_hash: str) -> ImagePreset | None:
    """現行レシピのhashだけを識別し、未知hashは ``None`` にする。"""

    normalized = recipe_hash.lower()
    for preset, recipe in _RECIPES.items():
        if recipe.recipe_hash == normalized:
            return preset
    return None


@dataclass(frozen=True, slots=True)
class ImageConfig:
    """実行時設定。出力品質値は選択したレシピから取得する。"""

    workers: int = 4
    dry_run: bool = False
    preset: ImagePreset = "standard"
    recipe: ImageRecipe = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError("workers must be at least 1")
        object.__setattr__(self, "recipe", image_recipe_for(self.preset))

    @property
    def max_long(self) -> int:
        return self.recipe.max_long

    @property
    def max_short(self) -> int:
        return self.recipe.max_short

    @property
    def quality(self) -> int:
        return self.recipe.quality

    @property
    def subsampling(self) -> int:
        return self.recipe.subsampling

    @property
    def optimize(self) -> bool:
        return self.recipe.optimize

    @property
    def progressive(self) -> bool:
        return self.recipe.progressive

    @property
    def recipe_hash(self) -> str:
        return self.recipe.recipe_hash


def default_output_dir(input_dir: Path) -> Path:
    """個別 CLI の既存既定値 ``<input>_resized`` を維持する。"""

    return Path(f"{input_dir}_resized")
