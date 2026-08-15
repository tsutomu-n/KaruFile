# /// script
# requires-python = ">=3.13"
# dependencies = []
# ///
"""KaruFile の通常 CLI 入口。"""
from __future__ import annotations

import sys

from orchestrator.shrink_all import main


if __name__ == "__main__":
    sys.exit(main())
