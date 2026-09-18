#!/usr/bin/env python3
"""Demo 00: send one issue to Gemini and print its free-form triage."""

from __future__ import annotations

import argparse

from google.genai import types

from demo_common import gemini_client, gemini_error_message, model_name

DEFAULT_ISSUE = "Nút thanh toán trả HTTP 500 với mọi thẻ Visa từ 14:30."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", default=DEFAULT_ISSUE, help="Nội dung issue cần phân loại.")
    args = parser.parse_args()

    try:
        # Keep the root Client alive until the synchronous request has completed.
        client = gemini_client()
        response = client.models.generate_content(
            model=model_name(),
            contents=args.issue,
            config=types.GenerateContentConfig(
                system_instruction="Bạn hỗ trợ phân loại issue phần mềm.",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
    except Exception as error:
        raise SystemExit(gemini_error_message(error)) from None

    print(response.text or "(Model không trả về nội dung văn bản.)")


if __name__ == "__main__":
    main()
