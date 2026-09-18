"""Application-controlled Issue Triage workflow shared by CLI and Streamlit demos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import types

COMPONENT_OWNERS = {
    "payment": "checkout-platform",
    "identity": "identity-platform",
    "search": "search-platform",
}
FUNCTION_DECLARATION = types.FunctionDeclaration(
    name="get_component_owner",
    description=(
        "Trả team chịu trách nhiệm cho một software component. "
        "Chỉ dùng component trong danh sách schema."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "component": types.Schema(
                type=types.Type.STRING,
                enum=list(COMPONENT_OWNERS),
            )
        },
        required=["component"],
    ),
)
FUNCTION_TOOLS = [types.Tool(function_declarations=[FUNCTION_DECLARATION])]
SYSTEM_PROMPT = (
    "Bạn hỗ trợ triage issue phần mềm. Khi cần biết team xử lý một component, "
    "hãy gọi get_component_owner. Component hợp lệ là payment, identity hoặc "
    "search. Không tự thực thi tool. Sau khi nhận kết quả tool, hãy trả lời "
    "ngắn gọn bằng tiếng Việt với severity, component và team xử lý."
)


@dataclass(frozen=True)
class ToolTrace:
    """One validated tool request and the application result returned to the model."""

    call_id: str
    name: str
    arguments: dict[str, Any]
    result: dict[str, str]


@dataclass(frozen=True)
class TriageResult:
    """Consumer-facing result of a complete, single-round Issue Triage run."""

    tool_traces: tuple[ToolTrace, ...]
    final_response: str


def get_component_owner(component: str) -> str:
    """Return the owner only for application-approved components."""
    return COMPONENT_OWNERS[component]


def execute_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, str]:
    """Validate a requested tool and its semantics before application execution."""
    if name != "get_component_owner":
        raise ValueError(f"Tool is not allowed: {name}")
    if set(arguments) != {"component"} or not isinstance(arguments["component"], str):
        raise ValueError("Tool arguments must contain exactly one string: component.")

    component = arguments["component"]
    if component not in COMPONENT_OWNERS:
        raise ValueError(f"Unknown component: {component}")

    return {"component": component, "owner": get_component_owner(component)}


def _first_turn_config() -> types.GenerateContentConfig:
    """Require exactly the approved function, while keeping execution in this app."""
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=FUNCTION_TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.ANY,
                allowed_function_names=["get_component_owner"],
            )
        ),
    )


def _final_turn_config() -> types.GenerateContentConfig:
    """Allow a text answer after the application has supplied the tool result."""
    return types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=FUNCTION_TOOLS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode=types.FunctionCallingConfigMode.NONE,
            )
        ),
    )


def triage_issue(client: genai.Client, model: str, issue: str) -> TriageResult:
    """Triage one issue, execute validated owner lookups, and return the final answer."""
    user_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=issue)],
    )
    first_response = client.models.generate_content(
        model=model,
        contents=[user_message],
        config=_first_turn_config(),
    )
    tool_calls = first_response.function_calls
    if not tool_calls:
        raise RuntimeError("Model returned no tool call despite the required tool configuration.")
    if not first_response.candidates or not first_response.candidates[0].content:
        raise RuntimeError("Model returned a tool call without conversation content.")

    traces: list[ToolTrace] = []
    function_response_parts: list[types.Part] = []
    for index, tool_call in enumerate(tool_calls, start=1):
        name = tool_call.name or ""
        arguments = dict(tool_call.args or {})
        result = execute_tool_call(name, arguments)
        traces.append(
            ToolTrace(
                call_id=tool_call.id or f"call-{index}",
                name=name,
                arguments=arguments,
                result=result,
            )
        )
        function_response_parts.append(
            types.Part.from_function_response(name=name, response=result)
        )

    history = [
        user_message,
        first_response.candidates[0].content,
        types.Content(role="user", parts=function_response_parts),
    ]
    final_response = client.models.generate_content(
        model=model,
        contents=history,
        config=_final_turn_config(),
    )
    return TriageResult(
        tool_traces=tuple(traces),
        final_response=final_response.text or "(Model không trả về nội dung văn bản.)",
    )
