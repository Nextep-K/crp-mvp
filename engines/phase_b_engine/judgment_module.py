"""
judgment_module.py — CRP 엔진 모듈 B (판단 모듈)

★ 규칙 4: LLM을 호출하는 유일한 모듈. 11항목 × ENSEMBLE_N=3 = 33회.
   비결정론적이며, 모듈 A가 mean/std로 안정화한다.

캐노니컬: 02 루브릭. 운영본: 05 프롬프트(p_f1.0). 재시도/에러: 06 §1.

설계: LLM 클라이언트를 주입(LLMClient)하여 호출부를 격리한다.
  - 실제 운영: AnthropicClient (Claude Sonnet 4, 09 §2 st.secrets API 키)
  - 테스트/오프라인: Mock 클라이언트 주입
모듈 A는 이 모듈을 import하지 않는다(단방향 의존, 03 독립 교체 원칙).

[명세 공백 — 충돌 reconcile, 플래그] evidence 누락 처리:
  02 §3.5는 "인용 없으면 0 처리"(L3/CI), 03은 "0 처리"(line58)와 "무효"(line82)가 병기.
  → CI(0~3): evidence 누락 시 score=0 (02 캐노니컬 "0 처리")
  → 1~10 항목: evidence 누락 시 무효(None) — 0은 1~10 척도 밖이라 03 "무효" 채택.
  조정 필요 시 _EVIDENCE_MISSING_POLICY 한 곳만 변경.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Optional, Protocol

from crp_types import Judgment, ClsSResult, DisengageResult
import prompts as P

# 06 §1.3 백오프 시퀀스 (초)
BACKOFF_TIMEOUT = [1, 4, 16]      # E001 LLM_API_TIMEOUT
_INVALID = object()               # 스키마 무효 센티넬
_EVIDENCE_MISSING_POLICY = "ci_zero_else_invalid"


class LLMClient(Protocol):
    """모듈 B가 의존하는 유일한 외부 경계. E001은 TimeoutError로 raise."""
    def complete(self, system: str, user: str, *,
                 temperature: float, max_tokens: int, timeout: int) -> str: ...


# ════════════════════════════════════════════════════════════════════════
# 파싱·검증
# ════════════════════════════════════════════════════════════════════════

def _parse_json(raw: str) -> Optional[dict]:
    """E004: JSON 파싱 실패 시 None."""
    if raw is None:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _has_evidence(item: str, obj: dict) -> bool:
    if obj.get("evidence"):
        return True
    # CI1은 early/late_quote, CI2는 vocab으로 근거 대체 가능 — evidence 키 우선, 없으면 보조 키
    if item == "ci1":
        return bool(obj.get("early_quote") or obj.get("late_quote"))
    if item == "ci2":
        return bool(obj.get("late_vocab") or obj.get("early_vocab"))
    return False


def _validate(item: str, obj: Optional[dict]):
    """반환: score(int) | None(정당한 null) | _INVALID(스키마 오류·재시도 대상)."""
    if obj is None or "score" not in obj:
        return _INVALID
    score = obj["score"]
    lo, hi = P.ITEM_SCALE[item]

    if score is None:
        return None  # 측정 불가(정당한 null) — 모듈 A가 평균에서 제외

    if not isinstance(score, int) or isinstance(score, bool):
        # 정수형 문자열/실수는 허용 변환 시도
        try:
            score = int(score)
        except (TypeError, ValueError):
            return _INVALID
    if not (lo <= score <= hi):
        return _INVALID

    # evidence 의무 (02/03/05). 누락 시 정책 분기.
    if not _has_evidence(item, obj):
        if P.ITEM_SCALE[item][0] == 0:   # CI 계열(0~3)
            return 0                      # 02 §3.5 "인용 없으면 0 처리"
        return None                       # 1~10 항목 → 무효(None)
    return score


# ════════════════════════════════════════════════════════════════════════
# 단일 항목 호출 (재시도 포함, 06 §1)
# ════════════════════════════════════════════════════════════════════════

def _call_with_timeout_retry(client: LLMClient, system: str, user: str,
                             temperature: float, sleep_fn: Callable[[float], None]) -> Optional[str]:
    """E001: 타임아웃 시 지수 백오프 [1,4,16] 최대 3회. 모두 실패 → None."""
    attempts = [0] + BACKOFF_TIMEOUT  # 최초 1 + 재시도 3
    for i, wait in enumerate(attempts):
        if wait:
            sleep_fn(wait)
        try:
            return client.complete(system, user,
                                   temperature=temperature,
                                   max_tokens=P.CALL_POLICY["max_tokens"],
                                   timeout=P.CALL_POLICY["timeout_sec"])
        except TimeoutError:
            if i == len(attempts) - 1:
                return None
            continue
    return None


def score_item(client: LLMClient, item: str, user_prompt: str,
               sleep_fn: Callable[[float], None] = time.sleep) -> Optional[int]:
    """한 항목 1회 채점. 반환: score(int) | None(무효/정당한 null)."""
    system = P.SYSTEM_PROMPTS[item]
    temp = P.CALL_POLICY["temperature"]

    raw = _call_with_timeout_retry(client, system, user_prompt, temp, sleep_fn)
    parsed = _parse_json(raw)

    if parsed is None:  # E004 파싱 실패 → temperature=0.1로 1회 재호출
        raw = _call_with_timeout_retry(
            client, system, user_prompt, P.CALL_POLICY["parse_retry_temperature"], sleep_fn)
        parsed = _parse_json(raw)
        if parsed is None:
            return None  # 무효

    result = _validate(item, parsed)
    if result is _INVALID:  # E005 스키마 오류 → 동일 입력 1회 재호출
        raw = _call_with_timeout_retry(client, system, user_prompt, temp, sleep_fn)
        parsed = _parse_json(raw)
        result = _validate(item, parsed) if parsed else _INVALID
        if result is _INVALID:
            return None  # 무효
    return result


# ════════════════════════════════════════════════════════════════════════
# 앙상블 실행 (33회) — 03 단계1
# ════════════════════════════════════════════════════════════════════════

def build_user_prompt(compressed: dict) -> str:
    md = compressed.get("metadata", {})
    return P.USER_TEMPLATE.format(
        grade=compressed.get("student_grade", ""),
        dept=compressed.get("department", ""),
        n_session=compressed.get("session_number", ""),
        n_student_turns=md.get("student_turn_count", ""),
        utterances_json=json.dumps(compressed.get("compressed_utterances", []),
                                   ensure_ascii=False),
    )


def run_judgment(client: LLMClient, compressed: dict,
                 ensemble_n: int = 3,
                 sleep_fn: Callable[[float], None] = time.sleep) -> list[Judgment]:
    """11항목 × ensemble_n회 → Judgment 리스트. 각 항목 무효 시 해당 칸 None.

    모듈 A의 aggregate_ensemble가 None을 평균에서 제외하므로,
    일부 호출 무효 시 유효 N이 자연 감소(05 '재실패 시 N=2 진행')한다.
    """
    user_prompt = build_user_prompt(compressed)
    runs: list[Judgment] = []
    for _ in range(ensemble_n):
        j = Judgment()
        for item in P.ALL_ITEMS:
            setattr(j, item, score_item(client, item, user_prompt, sleep_fn))
        runs.append(j)
    return runs


# ════════════════════════════════════════════════════════════════════════
# 보조 호출 (aux_prompts에서 사용) — 인터페이스
# ════════════════════════════════════════════════════════════════════════

def _aux_call(client: LLMClient, system: str, user: str,
              sleep_fn: Callable[[float], None]) -> Optional[dict]:
    raw = _call_with_timeout_retry(client, system, user,
                                   P.CALL_POLICY["temperature"], sleep_fn)
    parsed = _parse_json(raw)
    if parsed is None:
        raw = _call_with_timeout_retry(client, system, user,
                                       P.CALL_POLICY["parse_retry_temperature"], sleep_fn)
        parsed = _parse_json(raw)
    return parsed
