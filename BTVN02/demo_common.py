"""Shared configuration for the Google AI Studio Issue Triage demos."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import errors

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def configure_console_utf8() -> None:
    """Keep Vietnamese CLI output usable in Windows terminals with legacy code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


configure_console_utf8()


def load_environment() -> None:
    """Load the demo-local .env file without overriding OS environment variables."""
    load_dotenv(SCRIPT_DIRECTORY / ".env")
    # Demo 01 downloads tokenizer data only into the workspace if a cache is needed.
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(SCRIPT_DIRECTORY / ".tiktoken-cache"))


def model_name() -> str:
    """Return the configured Gemini model, with a sensible AI Studio default."""
    load_environment()
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def gemini_client() -> genai.Client:
    """Create a Google GenAI client authenticated with a Google AI Studio key."""
    load_environment()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is required. Copy .env.example to .env and set your Google AI Studio key."
        )
    return genai.Client(api_key=api_key)


def gemini_error_message(error: Exception) -> str:
    """Turn common Gemini API errors into safe, actionable Vietnamese messages."""
    if not isinstance(error, errors.APIError):
        return f"Không thể gọi Gemini: {error}"
    if error.code == 503:
        return (
            "Gemini đang quá tải (503). Thử GEMINI_MODEL=gemini-3.5-flash-lite "
            "hoặc chờ vài phút rồi chạy lại."
        )
    if error.code == 429:
        return "Đã chạm quota Gemini (429). Chờ quota làm mới rồi chạy lại."
    if error.code == 404:
        return "Không tìm thấy model. Kiểm tra lại GEMINI_MODEL trong .env."
    error_payload = error.details.get("error", error.details) if isinstance(error.details, dict) else {}
    detail_reasons = (
        [detail.get("reason") for detail in error_payload.get("details", []) if isinstance(detail, dict)]
        if isinstance(error_payload, dict)
        else []
    )
    if error.code == 400 and (
        error.status == "API_KEY_INVALID" or "API_KEY_INVALID" in detail_reasons
    ):
        return "API key không hợp lệ. Tạo/copy lại key từ Google AI Studio vào .env."
    if error.code == 400:
        return "Yêu cầu gửi tới Gemini không hợp lệ (400). Kiểm tra lại model và dữ liệu đầu vào."
    return f"Gemini API lỗi {error.code}: {error.message or error.status or 'không rõ nguyên nhân'}"
