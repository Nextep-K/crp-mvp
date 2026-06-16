"""
report_merger.py — Phase A/B 병렬 리포트 결합

Phase A 자기보고 점수와 Phase B 행동 측정 점수는 합산하지 않는다.
최종 리포트에는 두 결과를 병렬로 표시하고, 차이값만 비교 정보로 제공한다.
"""
from __future__ import annotations

DISALLOWED_COMBINED_KEYS = {
    "weighted_sum",
    "combined_score",
    "unified_index",
    "total_score",
    "final_combined_score",
}

TYPE_CUT = 5.5
GAP_TOLERANCE = 1.0


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _avg(history: list[dict], key: str):
    vals = []
    for item in history:
        value = _num(item.get(key))
        if value is not None:
            vals.append(value)
    return round(sum(vals) / len(vals), 2) if vals else None


def _gap_pattern(gap):
    if gap is None:
        return "측정 불가"
    if abs(gap) <= GAP_TOLERANCE:
        return "일치"
    if gap > GAP_TOLERANCE:
        return "겸손형"
    return "과신형"


def _classify_4_type(qli_score, mti_score):
    qli = _num(qli_score)
    mti = _num(mti_score)
    if qli is None or mti is None:
        return None
    q_high = qli >= TYPE_CUT
    m_high = mti >= TYPE_CUT
    if q_high and m_high:
        return "설계자형"
    if q_high and not m_high:
        return "상상가형"
    if not q_high and m_high:
        return "실행형"
    return "종속형"


def _type_consistency(phase_a_type, behavior_type):
    if not phase_a_type or not behavior_type:
        verdict = "판정 불가"
    elif phase_a_type == behavior_type:
        verdict = "일치"
    else:
        verdict = "불일치"
    return {
        "phase_a_type": phase_a_type,
        "behavior_type": behavior_type,
        "verdict": verdict,
    }


def generate_final_report(entry_profile: dict, metrics_history: list[dict]) -> dict:
    if not metrics_history:
        raise ValueError("metrics_history is required")

    latest = metrics_history[-1]
    avg_qli = _avg(metrics_history, "QLI")
    avg_mti = _avg(metrics_history, "MTI")
    entry_qli = _num(entry_profile.get("qli_axis_score"))
    entry_mti = _num(entry_profile.get("mti_axis_score"))

    qli_gap = round(avg_qli - entry_qli, 2) if avg_qli is not None and entry_qli is not None else None
    mti_gap = round(avg_mti - entry_mti, 2) if avg_mti is not None and entry_mti is not None else None
    behavior_type = _classify_4_type(avg_qli, avg_mti)

    report = {
        "entry_profile": dict(entry_profile),
        "crp_metrics": {
            "avg_QLI": avg_qli,
            "avg_MTI": avg_mti,
            "latest": latest,
            "history_count": len(metrics_history),
        },
        "comparison": {
            "self_vs_behavior_gap": {
                "qli_gap": qli_gap,
                "mti_gap": mti_gap,
                "qli_pattern": _gap_pattern(qli_gap),
                "mti_pattern": _gap_pattern(mti_gap),
                "QLI": qli_gap,
                "MTI": mti_gap,
            },
            "type_consistency": _type_consistency(entry_profile.get("entry_type"), behavior_type),
        },
        "rule": "Phase A and Phase B are displayed in parallel; no arithmetic combination is produced.",
    }
    _assert_no_disallowed_combination(report)
    return report


def _assert_no_disallowed_combination(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in DISALLOWED_COMBINED_KEYS:
                raise AssertionError(f"disallowed combined field detected: {key}")
            _assert_no_disallowed_combination(value)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_disallowed_combination(value)
