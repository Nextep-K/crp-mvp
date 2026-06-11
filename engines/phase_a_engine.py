"""
phase_a_engine.py — Phase A 자기 인식 진단 엔진

07_PhaseA/B 통합구조와 08_학습자유형분류 기준.
- 규칙 기반, LLM 없음.
- 4점 척도 응답을 축별 1~10 점수로 환산.
- Phase B 점수와 합산하지 않는다.
"""
from __future__ import annotations

from typing import Optional, Sequence

QUESTION_POOL_VERSION = "q_f1.0"
TYPE_NAMES = ("설계자형", "상상가형", "실행형", "종속형")


def _reverse_score(score: float) -> float:
    """4점 척도 역문항 변환: 1↔4, 2↔3."""
    return 5 - score


def _axis_score(items: Sequence[dict], axis: str) -> float:
    selected = [r for r in items if r.get("axis") == axis]
    if not selected:
        raise ValueError(f"{axis} responses are required")
    vals = []
    for r in selected:
        raw = float(r["score"])
        if raw < 1 or raw > 4:
            raise ValueError("Phase A score must be in 1..4")
        vals.append(_reverse_score(raw) if r.get("reverse") else raw)
    # 4점 평균을 1~10으로 선형 환산: 1→1, 4→10
    return round(1 + 9 * ((sum(vals) / len(vals) - 1) / 3), 2)


def classify_4_type(qli_score: float, mti_score: float,
                    population_median_qli: Optional[float] = None,
                    population_median_mti: Optional[float] = None,
                    population_n: int = 0) -> str:
    """08 §2.1. 모집단 <100이면 5.5 절대 기준."""
    q_cut = population_median_qli if population_n >= 100 and population_median_qli is not None else 5.5
    m_cut = population_median_mti if population_n >= 100 and population_median_mti is not None else 5.5
    q_high = qli_score >= q_cut
    m_high = mti_score >= m_cut
    if q_high and m_high:
        return "설계자형"
    if q_high and not m_high:
        return "상상가형"
    if not q_high and m_high:
        return "실행형"
    return "종속형"


def classify_12_subtype(qli_score: float, mti_score: float,
                        population_median_qli: Optional[float] = None,
                        population_median_mti: Optional[float] = None,
                        population_n: int = 0) -> str:
    """08 §3 골격 구현. 1순위 사분면 + 경계에 가까운 인접 사분면."""
    q_cut = population_median_qli if population_n >= 100 and population_median_qli is not None else 5.5
    m_cut = population_median_mti if population_n >= 100 and population_median_mti is not None else 5.5
    primary = classify_4_type(qli_score, mti_score, q_cut, m_cut, 100)
    dist_q = abs(qli_score - q_cut)
    dist_m = abs(mti_score - m_cut)
    q_high = qli_score >= q_cut
    m_high = mti_score >= m_cut
    if abs(dist_q - dist_m) < 0.3:
        secondary = "대각경계"
    elif dist_q < dist_m:
        secondary = classify_4_type(q_cut - 0.01 if q_high else q_cut + 0.01, mti_score, q_cut, m_cut, 100)
    else:
        secondary = classify_4_type(qli_score, m_cut - 0.01 if m_high else m_cut + 0.01, q_cut, m_cut, 100)
    return f"{primary}-{secondary}"


def phase_a_score(responses: Sequence[dict], *,
                  population_median_qli: Optional[float] = None,
                  population_median_mti: Optional[float] = None,
                  population_n: int = 0,
                  question_pool_version: str = QUESTION_POOL_VERSION) -> dict:
    """Phase A 결과(entry_profile) 생성. Phase B metrics와 결합하지 않는다."""
    qli = _axis_score(responses, "qli")
    mti = _axis_score(responses, "mti")
    entry_type = classify_4_type(qli, mti, population_median_qli, population_median_mti, population_n)
    return {
        "qli_axis_score": qli,
        "mti_axis_score": mti,
        "entry_type": entry_type,
        "entry_subtype": classify_12_subtype(qli, mti, population_median_qli, population_median_mti, population_n),
        "question_pool_version": question_pool_version,
        "responses": list(responses),
    }
