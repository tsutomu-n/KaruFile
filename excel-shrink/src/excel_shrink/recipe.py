"""Validated image size/encoding requests, independent of workbook layout."""


def resolve_recipe(dpi: int | None, max_side: int | None,
                   jpeg_quality: int | None) -> tuple[int | None, int | None, int]:
    if dpi is None and max_side is None:
        max_side = 800
    if jpeg_quality is None:
        jpeg_quality = 72 if max_side is not None else 85
    validate_recipe(dpi, max_side, jpeg_quality)
    return dpi, max_side, jpeg_quality


def validate_recipe(dpi: int | None, max_side: int | None, jpeg_quality: int) -> None:
    if max_side is None:
        if type(dpi) is not int or not 150 <= dpi <= 300:
            raise ValueError("--dpi must be an integer from 150 to 300")
    elif type(max_side) is not int or not 100 <= max_side <= 10000 or dpi is not None:
        raise ValueError("--max-side must be an integer from 100 to 10000 and excludes --dpi")
    if type(jpeg_quality) is not int or not 40 <= jpeg_quality <= 95:
        raise ValueError("--jpeg-quality must be an integer from 40 to 95")


def capped_size(size: tuple[int, int], cap: int) -> tuple[int, int]:
    longest = max(size)
    if longest <= cap:
        return size
    return tuple(max(1, (n * cap + longest // 2) // longest) for n in size)
