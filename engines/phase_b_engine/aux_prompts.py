"""
aux_prompts.py — 보조 LLM 호출 (05 §보조, 09 §3 measure_worker 내장)

CLS-S    : B1 규칙 분류 신뢰도 < 0.6 경계 발화만 Class S 보조 판정.
DISENGAGE: 모듈 A 1차 플래그(4조건 2개+) 세션만 2차 의미 검증.

두 호출 모두 모듈 B 경계(LLM)에 속한다. 비용 최소화를 위해 조건부로만 호출한다.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

import prompts as P
from crp_types import ClsSResult, DisengageResult
from judgment_module import LLMClient, _aux_call


def classify_class_s(client: LLMClient, target_utterance: str,
                     context_before: list, rule_based_label: str,
                     sleep_fn: Callable[[float], None] = time.sleep) -> ClsSResult:
    """class_confidence < 0.6 경계 발화에만 호출. confidence<0.7이면 보수적 false."""
    user = json.dumps({
        "target_utterance": target_utterance,
        "context_before": context_before,
        "rule_based_label": rule_based_label,
    }, ensure_ascii=False)

    obj = _aux_call(client, P.AUX_PROMPTS["cls_s"], user, sleep_fn)
    if obj is None:
        # 무효 시 규칙 라벨 유지 (보조 판정 실패는 원 라벨을 바꾸지 않음)
        return ClsSResult(is_class_s=False, fallback_label=rule_based_label,
                          reason="aux_call_failed")
    conf = float(obj.get("confidence", 0.0) or 0.0)
    is_s = bool(obj.get("is_class_s", False)) and conf >= 0.7  # 05 절대규칙3 보수적
    return ClsSResult(
        is_class_s=is_s,
        sub_label=obj.get("sub_label") if is_s else None,
        confidence=conf,
        fallback_label=obj.get("fallback_label") if not is_s else None,
        reason=obj.get("reason", ""),
    )


def detect_disengagement_llm(client: LLMClient, utterances: list,
                             sleep_fn: Callable[[float], None] = time.sleep) -> DisengageResult:
    """모듈 A 1차 플래그 세션만 호출(06 §9 2단계). severity moderate+ → 측정 제외."""
    student_utts = [u for u in utterances if u.get("speaker") == "student"]
    user = json.dumps({"compressed_utterances": student_utts}, ensure_ascii=False)

    obj = _aux_call(client, P.AUX_PROMPTS["disengage"], user, sleep_fn)
    if obj is None:
        # 무효 시 회피로 단정하지 않음(보수적). 1차 플래그는 별도 기록되어 있음.
        return DisengageResult(severity="none", reason="aux_call_failed")
    return DisengageResult(
        disengagement_detected=bool(obj.get("disengagement_detected", False)),
        severity=obj.get("severity", "none") or "none",
        engaged_ratio=float(obj.get("engaged_ratio", 1.0) or 1.0),
        signals=obj.get("signals", []) or [],
        reason=obj.get("reason", ""),
    )
