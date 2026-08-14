from shrink_all import build_parser, human_size, parse_image_summary


def test_human_size_formats_units():
    assert human_size(500) == "500.00 B"
    assert human_size(1536) == "1.50 KB"


def test_parse_image_summary_extracts_count_and_sizes():
    lines = [
        "some log line",
        "Resized 12 images (1 errors)",
        "  3.00 MB -> 1.20 MB",
    ]
    result = parse_image_summary(lines)
    assert result == {
        "count": 12,
        "errors": 1,
        "orig_size": 3 * 1024 * 1024,
        "new_size": int(1.2 * 1024 * 1024),
    }


def test_parse_image_summary_returns_none_without_summary_line():
    assert parse_image_summary(["no summary here"]) is None


def test_build_parser_requires_input():
    parser = build_parser()
    args = parser.parse_args(["-i", "C:\\some\\path"])
    assert args.input == "C:\\some\\path"
    assert args.pdf_workers == 2
    assert args.image_workers == 4
