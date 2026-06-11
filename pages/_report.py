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
    gap = report["comparison"]["self_vs_behavior_gap"]
    consistency = report["comparison"]["type_consistency"]
    latest = metrics_history[-1]

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
    c5.metric("행동 유형", consistency["behavior_type"] or "판정 불가")

    st.divider()

    # ── Gap 비교 ────────────────────────────────────────────────────
    st.subheader("자기 인식 vs 실제 행동 비교")
    st.caption("gap = 행동 측정값 − 자기보고값. 결합·합산이 아닙니다.")
    g1, g2 = st.columns(2)
    qli_gap = gap["qli_gap"]
    mti_gap = gap["mti_gap"]
    g1.metric("QLI gap", f"{qli_gap:+.2f}" if qli_gap is not None else "-",
              delta=gap["qli_pattern"])
    g2.metric("MTI gap", f"{mti_gap:+.2f}" if mti_gap is not None else "-",
              delta=gap["mti_pattern"])

    type_v = consistency["verdict"]
    if type_v == "일치":
        st.success(f"✅ 유형 일치: 자기 인식과 행동이 정합합니다 ({consistency['phase_a_type']})")
    elif type_v == "불일치":
        st.warning(f"⚠️ 유형 불일치: 자기 인식({consistency['phase_a_type']}) ≠ "
                   f"행동({consistency['behavior_type']}). 교수 면담을 권장합니다.")

    _gap_guidance = {
        "일치": "자기 인식과 실제 행동이 일치합니다. 메타인지적 자기 이해가 정확합니다.",
        "겸손형": "실제 역량이 자기 평가보다 높습니다. 자신감을 가져도 좋습니다.",
        "과신형": "자기 평가가 실제 행동보다 높습니다. 행동 증거를 다시 살펴보세요.",
    }
    if gap["qli_pattern"] in _gap_guidance:
        st.info(f"**QLI**: {_gap_guidance[gap['qli_pattern']]}")
