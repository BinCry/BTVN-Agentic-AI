#!/usr/bin/env python3
"""Demo 03: application-controlled function calling with Gemini."""

from __future__ import annotations

import argparse
import json

from demo_common import gemini_client, gemini_error_message, model_name
from triage_workflow import triage_issue

DEFAULT_ISSUE = (
    "Nút thanh toán trả HTTP 500 với mọi thẻ Visa từ 14:30. "
    "Hãy triage issue và cho biết team nào cần xử lý."
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", default=DEFAULT_ISSUE, help="Nội dung issue cần triage.")
    args = parser.parse_args()

    try:
        result = triage_issue(gemini_client(), model_name(), args.issue)
    except Exception as error:
        raise SystemExit(gemini_error_message(error)) from None
    for trace in result.tool_traces:
        print("=== 1. Model đề xuất tool call ===")
        print(
            json.dumps(
                {
                    "id": trace.call_id,
                    "name": trace.name,
                    "arguments": trace.arguments,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("\n=== 2. Application thực thi ===")
        print(
            f"get_component_owner({trace.result['component']!r}) "
            f"-> {trace.result['owner']!r}"
        )
        print("\n=== 3. Tool result quay lại model ===")
        print(json.dumps(trace.result, ensure_ascii=False, indent=2))

    print("\n=== Final response ===")
    print(result.final_response)


if __name__ == "__main__":
    main()
