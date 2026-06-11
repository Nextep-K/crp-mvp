"""
report_merger.py — Phase A/B 병렬 리포트 결합

07 핵심 원칙: Phase A 자기보고 점수와 Phase B 행동 측정 점수는
합산·평균·가중 결합하지 않는다. 차이(self_vs_behavior_gap)만 계산한다.
"""
from __future__ import annotations

BANNED_FIELDS = {"weighted_sum", "combined_score", "unified_index", "total_score", "final_combined_score"}


def _avg(history: list[dict], key: str):
    vals = [h.get(key) for h in history if h.get(key) is not None]
    return sum(vals) / len(vals) if vals else None


def generate_final_report(entry_profile: dict, metrics_history: list[dict]) -> dict:
    if not metrics_history:
        raise ValueError("metrics_history is required")
    latest = metrics_history[-1]
    behavior_summary = {
        "avg_QLI": _avg(metrics_history, "QLI"),
        "avg_MTI": _avg(metrics_history, "MTI"),
        "latest": latest,
        "history_count": len(metrics_history),
    }
    q_gap = None
    m_gap = None
    if behavior_summary["avg_QLI"] is not None:
        q_gap = round(behavior_summary["avg_QLI"] - entry_profile.get("qli_axis_score", 0), 2)
    if behavior_summary["avg_MTI"] is not None:
        m_gap = round(behavior_summary["avg_MTI"] - entry_profile.get("mti_axis_score", 0), 2)
    report = {
        "entry_profile": dict(entry_profile),
        "crp_metrics": behavior_summary,
        "comparison": {
            "self_vs_behavior_gap": {
                "QLI": q_gap,
                "MTI": m_gap,
            },
            "type_consistency": "not_evaluated" if q_gap is None or m_gap is None else "compare_gap_only",
        },
        "rule": "Phase A and Phase B are displayed in parallel; no arithmetic combination is produced.",
    }
    _assert_no_combination(report)
    return report


def _assert_no_combination(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in BANNED_FIELDS:
                raise AssertionError(f"banned combination field detected: {k}")
            _assert_no_combination(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_combination(v)
