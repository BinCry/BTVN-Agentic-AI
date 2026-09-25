#!/usr/bin/env python3
"""Demo 02: contrast prompt-only JSON with Gemini structured output."""

from __future__ import annotations

import argparse
import json
from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field

from demo_common import gemini_client, gemini_error_message, model_name

DEFAULT_ISSUE = "Nút thanh toán trả HTTP 500 với mọi thẻ Visa từ 14:30."


class IssueTriage(BaseModel):
    """The machine-readable contract between this demo and the model."""

    status: Literal["classified", "insufficient_data", "out_of_scope"]
    severity: Literal["P0", "P1", "P2", "P3"] | None = None
    component: str | None = None
    needs_urgent_response: bool = False
    reason: str = Field(description="Lý do ngắn gọn dựa trên dữ liệu issue")


SYSTEM_PROMPT = """Bạn là kỹ sư phụ trách phân loại sự cố phần mềm.
Phân loại severity theo P0/P1/P2/P3 dựa trên dữ liệu issue. Nếu dữ liệu không
đủ để phân loại, dùng status=insufficient_data thay vì đoán. Chỉ dùng
status=out_of_scope khi nội dung không phải issue phần mềm."""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", default=DEFAULT_ISSUE, help="Nội dung issue cần phân loại.")
    args = parser.parse_args()

    contents = f"{args.issue}\n\nChỉ trả về một JSON object đúng schema."

    try:
        client = gemini_client()
        model = model_name()
        prompt_only = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
    except Exception as error:
        raise SystemExit(gemini_error_message(error)) from None
    print("=== Prompt-only response ===")
    print(prompt_only.text or "(Model không trả về nội dung văn bản.)")

    try:
        constrained = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=IssueTriage,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
    except Exception as error:
        raise SystemExit(gemini_error_message(error)) from None
    if not constrained.text:
        raise RuntimeError("Model did not return a structured IssueTriage response.")
    payload = json.loads(constrained.text)
    if not isinstance(payload, dict):
        raise RuntimeError("Structured response must be a JSON object.")
    unexpected_fields = set(payload) - set(IssueTriage.model_fields)
    if unexpected_fields:
        raise RuntimeError(f"Structured response contains unexpected fields: {unexpected_fields}")
    parsed = IssueTriage.model_validate(payload)

    print("\n=== Constrained structured response ===")
    print(parsed.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
