"""
pages/_report.py — 종합 결과 리포트 (07 §4.2, 09 §4)

학기말에만 공개. Phase A(자기보고) + Phase B(행동 측정) 병렬 표시.
self_vs_behavior_gap 해석 포함. 합산·결합 없음(규칙 5).
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

import streamlit as st
import db
import report_merger as RM
import phase_a_engine as PA


def _gap_value(gap: dict, lower_key: str, legacy_key: str):
    return gap.get(lower_key) if lower_key in gap else gap.get(legacy_key)


def _gap_pattern(value):
    if value is None:
        return "측정 불가"
    if abs(value) <= 1.0:
        return "일치"
    if value > 1.0:
        return "겸손형"
    return "과신형"


def _behavior_type(latest: dict, consistency):
    if isinstance(consistency, dict):
        return consistency.get("behavior_type")
    qli = latest.get("QLI")
    mti = latest.get("MTI")
    if qli is None or mti is None:
        return None
    return PA.classify_4_type(float(qli), float(mti))


def _type_verdict(ep: dict, behavior_type: str | None, consistency):
    if isinstance(consistency, dict):
        return consistency.get("verdict") or "판정 불가"
    if not behavior_type:
        return "판정 불가"
    return "일치" if ep.get("entry_type") == behavior_type else "불일치"


def render(conn, user_id: str, course_id: str):
    st.title("학기 종합 리포트")
    st.caption("자기보고(Phase A)와 실제 행동(Phase B) 비교 — 합산이 아닌 대조입니다.")

    ep = db.load_latest_phase_a(conn, user_id, course_id)
    metrics_history = db.load_metrics_history(conn, user_id, course_id,
                                              n=20, exclude_disengaged=True)

    if not ep:
        st.info("Phase A 진단 결과가 없습니다.")
        return
    if not metrics_history:
        st.info("아직 측정된 Phase B 세션이 없습니다. 세션을 완료한 후 다시 확인하세요.")
        return

    report = RM.generate_final_report(ep, metrics_history)
    gap = report.get("comparison", {}).get("self_vs_behavior_gap", {})
    consistency = report.get("comparison", {}).get("type_consistency", {})
    latest = metrics_history[-1]
    behavior_type = _behavior_type(latest, consistency)
    verdict = _type_verdict(ep, behavior_type, consistency)

    # ── Phase A ──────────────────────────────────────────────────────
    st.subheader("Phase A — 자기 인식 (학기 초 진단)")
    c1, c2 = st.columns(2)
    c1.metric("QLI 자기 평가", f"{ep['qli_axis_score']:.1f} / 10")
    c2.metric("MTI 자기 평가", f"{ep['mti_axis_score']:.1f} / 10")
    st.caption(f"진단 유형(자기보고): **{ep['entry_type']}**")

    st.divider()

    # ── Phase B 시계열 ───────────────────────────────────────────────
    st.subheader("Phase B — 행동 측정 (세션별 변화)")
    metric_keys = ["MTI", "QLI", "Rec", "Recon", "Orc"]
    chart_data = {k: [m.get(k) for m in metrics_history] for k in metric_keys}
    import pandas as pd
    df = pd.DataFrame(chart_data).dropna(how="all")
    if not df.empty:
        st.line_chart(df, height=260)

    c3, c4, c5 = st.columns(3)
    c3.metric("최근 MTI", f"{latest.get('MTI', '-')}")
    c4.metric("최근 QLI", f"{latest.get('QLI', '-')}")
    c5.metric("행동 유형", behavior_type or "판정 불가")

    st.divider()

    # ── Gap 비교 ────────────────────────────────────────────────────
    st.subheader("자기 인식 vs 실제 행동 비교")
    st.caption("gap = 행동 측정값 − 자기보고값. 결합·합산이 아닙니다.")
    g1, g2 = st.columns(2)
    qli_gap = _gap_value(gap, "qli_gap", "QLI")
    mti_gap = _gap_value(gap, "mti_gap", "MTI")
    qli_pattern = gap.get("qli_pattern") or _gap_pattern(qli_gap)
    mti_pattern = gap.get("mti_pattern") or _gap_pattern(mti_gap)
    g1.metric("QLI gap", f"{qli_gap:+.2f}" if qli_gap is not None else "-",
              delta=qli_pattern)
    g2.metric("MTI gap", f"{mti_gap:+.2f}" if mti_gap is not None else "-",
              delta=mti_pattern)

    if verdict == "일치":
        st.success(f"유형 일치: 자기 인식과 행동이 정합합니다 ({ep['entry_type']})")
    elif verdict == "불일치":
        st.warning(f"유형 불일치: 자기 인식({ep['entry_type']}) ≠ "
                   f"행동({behavior_type or '판정 불가'}). 교수 면담을 권장합니다.")
    else:
        st.info("유형 일치 여부는 아직 판정할 수 없습니다.")

    _gap_guidance = {
        "일치": "자기 인식과 실제 행동이 일치합니다. 메타인지적 자기 이해가 정확합니다.",
        "겸손형": "실제 역량이 자기 평가보다 높습니다. 자신감을 가져도 좋습니다.",
        "과신형": "자기 평가가 실제 행동보다 높습니다. 행동 증거를 다시 살펴보세요.",
    }
    if qli_pattern in _gap_guidance:
        st.info(f"**QLI**: {_gap_guidance[qli_pattern]}")
    if mti_pattern in _gap_guidance:
        st.info(f"**MTI**: {_gap_guidance[mti_pattern]}")
