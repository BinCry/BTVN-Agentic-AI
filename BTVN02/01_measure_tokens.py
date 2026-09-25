#!/usr/bin/env python3
"""Demo 01: compare English and Vietnamese token counts across tokenizers."""

from __future__ import annotations

import tiktoken

from demo_common import load_environment

ENGLISH = (
    "The Aqueduct of Segovia is a Roman aqueduct in Segovia, Spain. "
    "It was built around the first century AD to channel water from "
    "springs in the mountains seventeen kilometres away."
)
VIETNAMESE = (
    "Cầu máng Segovia là một cầu máng dẫn nước của người La Mã tại "
    "Segovia, Tây Ban Nha. Công trình được xây dựng vào khoảng thế kỷ "
    "thứ nhất sau Công nguyên để dẫn nước từ các con suối trên núi "
    "cách đó mười bảy ki-lô-mét."
)


def main() -> None:
    # Keeps environment handling consistent with the API demos; no API call is made here.
    load_environment()

    for name in ("cl100k_base", "o200k_base"):
        encoding = tiktoken.get_encoding(name)
        english_tokens = len(encoding.encode(ENGLISH))
        vietnamese_tokens = len(encoding.encode(VIETNAMESE))
        print(
            f"{name}: EN={english_tokens} VI={vietnamese_tokens} "
            f"ratio={vietnamese_tokens / english_tokens:.2f}"
        )


if __name__ == "__main__":
    main()
