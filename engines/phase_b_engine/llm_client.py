"""
llm_client.py — 실제 Anthropic API 클라이언트 (09 §2, 09 §4)

LLMClient 프로토콜(judgment_module.py)의 실운영 구현체.
API 키: .streamlit/secrets.toml ANTHROPIC_API_KEY (절대 코드에 하드코딩 금지).
TimeoutError는 그대로 raise → judgment_module의 E001 백오프가 처리.
"""
from __future__ import annotations

import os

import anthropic
import prompts as P

try:
    import streamlit as st
except Exception:  # pragma: no cover - non-Streamlit test/runtime fallback
    st = None


def _get_model_name() -> str:
    """Return the Anthropic model ID, allowing deployment-time override."""
    env_model = os.getenv("ANTHROPIC_MODEL", "").strip()
    if env_model:
        return env_model

    if st is not None:
        try:
            secret_model = str(st.secrets.get("ANTHROPIC_MODEL", "")).strip()
            if secret_model:
                return secret_model
        except Exception:
            pass

    return P.CALL_POLICY["model"]


class AnthropicClient:
    """Anthropic SDK 래퍼. judgment_module.LLMClient 프로토콜 구현."""

    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(self, system: str, user: str, *,
                 temperature: float, max_tokens: int, timeout: int) -> str:
        """단일 완성 호출. 타임아웃 초과 시 TimeoutError raise."""
        try:
            msg = self._client.messages.create(
                model=_get_model_name(),
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                temperature=temperature,
                timeout=timeout,
            )
            return msg.content[0].text
        except anthropic.APITimeoutError as e:
            raise TimeoutError(str(e)) from e
