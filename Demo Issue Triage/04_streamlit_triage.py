#!/usr/bin/env python3
"""Demo 04: Streamlit UI for Issue Triage with Gemini function calling."""

from __future__ import annotations

import os

import streamlit as st

from demo_common import gemini_client, gemini_error_message, load_environment, model_name
from triage_workflow import TriageResult, triage_issue

DEFAULT_ISSUE = """Nút thanh toán trả HTTP 500 với mọi thẻ Visa từ 14:30.
Hãy triage issue và cho biết team nào cần xử lý."""

st.set_page_config(
    page_title="Issue Triage — Gemini Function Calling",
    page_icon="IT",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
    [data-testid="stFormSubmitButton"] > button {
        background-color: #15803d;
        color: #ffffff;
    }
    [data-testid="stFormSubmitButton"] > button:hover {
        background-color: #166534;
        color: #ffffff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_result(result: TriageResult) -> None:
    """Render the machine-visible tool trace before the model's final response."""
    first_trace = result.tool_traces[0]
    component_column, owner_column = st.columns(2)
    component_column.metric("Component đã xác thực", first_trace.result["component"])
    owner_column.metric("Team phụ trách", first_trace.result["owner"])

    with st.expander("Trace function calling", expanded=True):
        for index, trace in enumerate(result.tool_traces, start=1):
            st.markdown(f"**{index}. Model yêu cầu tool** `{trace.name}`")
            st.json({"id": trace.call_id, "arguments": trace.arguments})
            st.markdown("**Application validate và thực thi**")
            st.json(trace.result)

    st.subheader("Kết quả triage")
    st.markdown(result.final_response)


def main() -> None:
    load_environment()

    with st.sidebar:
        st.header("Runtime")
        st.write("Google AI Studio / Gemini API")
        st.write("Model")
        st.code(os.getenv("GEMINI_MODEL") or model_name(), language=None)
        st.divider()
        st.write(
            "Application chỉ thực thi get_component_owner cho payment, identity và search."
        )

    st.title("Issue Triage")
    st.write("Demo 04 — model đề xuất tool call; application kiểm tra rồi mới thực thi.")

    with st.form("issue-triage-form"):
        issue = st.text_area(
            "Mô tả issue",
            value=DEFAULT_ISSUE,
            height=220,
            help="Nêu symptom, phạm vi ảnh hưởng và thời điểm bắt đầu nếu có.",
        )
        submitted = st.form_submit_button("Phân loại issue", type="primary", use_container_width=True)

    if not submitted:
        return
    if not issue.strip():
        st.error("Nhập mô tả issue trước khi chạy triage.")
        return

    try:
        with st.spinner("Đang gọi Gemini và xử lý tool request…"):
            result = triage_issue(gemini_client(), model_name(), issue.strip())
    except Exception as error:
        st.error(gemini_error_message(error))
        st.info("Kiểm tra GEMINI_MODEL, quota và quyền truy cập model trong .env.")
        return

    st.success("Application đã hoàn tất function-calling flow.")
    render_result(result)


if __name__ == "__main__":
    main()
