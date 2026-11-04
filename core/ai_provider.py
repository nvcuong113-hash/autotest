from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


class AIProviderError(RuntimeError):
    """Safe, user-facing AI provider error. Never includes API keys or request payloads."""


@dataclass(frozen=True)
class AIProviderStatus:
    provider: str
    model: str
    configured: bool
    api_key_variable: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_ai_status() -> AIProviderStatus:
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower() or "gemini"
    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    configured = bool(os.getenv("GEMINI_API_KEY", "").strip())
    if provider != "gemini":
        return AIProviderStatus(
            provider=provider,
            model=model,
            configured=False,
            api_key_variable="GEMINI_API_KEY",
            message="Provider chưa được hỗ trợ; hiện AutoTest chỉ bật Gemini.",
        )
    if not configured:
        return AIProviderStatus(
            provider="gemini",
            model=model,
            configured=False,
            api_key_variable="GEMINI_API_KEY",
            message="Chưa cấu hình GEMINI_API_KEY. Chức năng phân tích/sinh bằng AI đang tắt; parser cục bộ vẫn dùng được.",
        )
    return AIProviderStatus(
        provider="gemini",
        model=model,
        configured=True,
        api_key_variable="GEMINI_API_KEY",
        message="Gemini đã được cấu hình.",
    )


def parse_json_response(text: str) -> Any:
    """Parse strict JSON or JSON surrounded by a Markdown code fence."""
    raw = str(text or "").strip()
    if not raw:
        raise AIProviderError("Gemini trả về nội dung rỗng.")
    raw = re.sub(r"^\`\`\`(?:json)?\\s*|\\s*\`\`\`$", "", raw, flags=re.IGNORECASE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, character in enumerate(raw):
            if character not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise AIProviderError("Gemini không trả về JSON hợp lệ. Hãy thử lại với tài liệu/phạm vi nhỏ hơn.")


class GeminiProvider:
    """Small provider adapter; callers depend on JSON output, not on a vendor SDK."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("GEMINI_API_KEY", "")).strip()
        self.model = (model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)).strip()
        if not self.api_key:
            raise AIProviderError(
                "Thiếu GEMINI_API_KEY. Hãy tạo API key trong Google AI Studio và thêm vào Environment của AutoTest."
            )
        if os.getenv("AI_PROVIDER", "gemini").strip().lower() not in {"", "gemini"}:
            raise AIProviderError("AI_PROVIDER hiện chỉ hỗ trợ giá trị 'gemini'.")
        if not self.model:
            self.model = DEFAULT_GEMINI_MODEL

    def generate_json(
        self,
        prompt: str,
        response_schema: dict[str, Any] | None = None,
        max_output_tokens: int = 8192,
    ) -> Any:
        try:
            from google import genai
        except ImportError as exc:
            raise AIProviderError(
                "Thiếu thư viện google-genai. Hãy cài requirements.txt và deploy lại AutoTest."
            ) from exc

        config: dict[str, Any] = {
            "response_mime_type": "application/json",
            "max_output_tokens": max(256, min(int(max_output_tokens), 16384)),
        }
        if response_schema:
            config["response_json_schema"] = response_schema

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            return parse_json_response(getattr(response, "text", "") or "")
        except AIProviderError:
            raise
        except Exception as exc:
            error_name = type(exc).__name__.lower()
            error_text = str(exc).lower()
            if "429" in error_text or "resource_exhausted" in error_text or "quota" in error_text:
                message = "Gemini đã chạm quota/rate limit của gói hiện tại. Chờ quota hồi phục hoặc giảm số yêu cầu mỗi lần."
            elif "401" in error_text or "403" in error_text or "api key" in error_text or "permission" in error_text:
                message = "Gemini từ chối API key hoặc quyền truy cập model. Kiểm tra GEMINI_API_KEY và quyền Gemini API."
            elif "timeout" in error_name or "deadline" in error_text:
                message = "Gemini hết thời gian phản hồi. Hãy chia tài liệu thành phạm vi nhỏ hơn rồi thử lại."
            else:
                message = f"Không gọi được Gemini ({type(exc).__name__}). Kiểm tra model, quota và log triển khai."
            raise AIProviderError(message) from None


def get_ai_provider(api_key: str | None = None, model: str | None = None) -> GeminiProvider:
    status = get_ai_status()
    if status.provider != "gemini":
        raise AIProviderError(status.message)
    return GeminiProvider(api_key=api_key, model=model)
