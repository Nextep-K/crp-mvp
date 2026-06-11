"""
pages/_dashboard.py — 교수 대시보드 (06 §2~3, 09 §6)

전체 학생 시계열, 신뢰도 플래그(low_reliability·disengagement),
수동 검토 큐(confirm/remeasure/reject). 실시간 모니터링용.
"""
from __future__ import annotations
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

import streamlit as st
import db


def render(conn, prof_id: str, course_id: str):
    st.title("교수 대시보드")
    st.caption(f"과목: {course_id}")

    # ── 전체 측정 현황 ────────────────────────────────────────────────
    rows = conn.execute("""
        SELECT sm.student_id, sm.mti, sm.qli, sm.rec, sm.recon, sm.orc,
               sm.qualitative_band_mti, sm.disengagement_flag,
               sm.low_reliability, sm.rubric_version, sm.created_at,
               sm.metric_id, sm.crp_output
        FROM session_metrics sm
        WHERE sm.course_id=?
        ORDER BY sm.created_at DESC
    """, (course_id,)).fetchall()

    import pandas as pd

    # 측정 결과가 아직 없어도, 제출된 세션의 큐 상태는 교수 화면에 보여준다.
    if not rows:
        st.info("아직 측정 결과가 없습니다.")
        st.subheader("⏳ 측정 큐 상태")
        q_rows = conn.execute("""
            SELECT mq.status, COUNT(*) as cnt
            FROM measure_queue mq
            JOIN sessions s ON s.id = mq.session_id
            WHERE s.course_id=?
            GROUP BY mq.status
        """, (course_id,)).fetchall()
        if q_rows:
            st.dataframe(pd.DataFrame([dict(r) for r in q_rows]), hide_index=True)
            pending = conn.execute("""
                SELECT mq.job_id, mq.status, s.student_id, s.id AS session_id,
                       s.status AS session_status, s.session_start, s.session_end, mq.created_at
                FROM measure_queue mq
                JOIN sessions s ON s.id = mq.session_id
                WHERE s.course_id=?
                ORDER BY mq.created_at DESC
            """, (course_id,)).fetchall()
            st.dataframe(pd.DataFrame([dict(r) for r in pending]), hide_index=True)
        else:
            st.write("큐가 비어 있습니다.")
        return

    df = pd.DataFrame([dict(r) for r in rows])

    # ── 요약 지표 ─────────────────────────────────────────────────────
    st.subheader("측정 현황 요약")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 세션", len(df))
    c2.metric("측정 회피 탐지", int(df["disengagement_flag"].sum()))
    low_rel = conn.execute("""
        SELECT COUNT(*) FROM session_metrics
        WHERE course_id=? AND low_reliability=1
    """, (course_id,)).fetchone()[0]
    c3.metric("신뢰도 낮음", low_rel)
    grok_count = sum(
        1 for r in rows
        if json.loads(r["crp_output"]).get("grokking", {}).get("detected")
    )
    c4.metric("Grokking 탐지", grok_count)

    # ── 학생별 시계열 ─────────────────────────────────────────────────
    st.subheader("학생별 MTI 시계열")
    students = df["student_id"].unique().tolist()
    selected = st.multiselect("학생 선택", students, default=students[:5])
    if selected:
        timeline = {}
        for sid in selected:
            s_rows = conn.execute("""
                SELECT mti, qli, created_at FROM session_metrics
                WHERE course_id=? AND student_id=? AND disengagement_flag=0
                ORDER BY created_at ASC
            """, (course_id, sid)).fetchall()
            if s_rows:
                timeline[sid] = [r["mti"] for r in s_rows]
        if timeline:
            max_len = max(len(v) for v in timeline.values())
            padded = {k: v + [None]*(max_len-len(v)) for k, v in timeline.items()}
            st.line_chart(pd.DataFrame(padded), height=260)

    # ── 플래그 목록 ────────────────────────────────────────────────────
    st.subheader("🚩 신뢰도 플래그 세션")
    flag_rows = conn.execute("""
        SELECT metric_id, student_id, mti, qli, disengagement_flag,
               low_reliability, created_at, crp_output
        FROM session_metrics
        WHERE course_id=? AND (disengagement_flag=1 OR low_reliability=1)
        ORDER BY created_at DESC
    """, (course_id,)).fetchall()

    if not flag_rows:
        st.write("현재 플래그 세션이 없습니다.")
    else:
        for r in flag_rows:
            out = json.loads(r["crp_output"])
            rel = out.get("reliability", {})
            flags = []
            if r["disengagement_flag"]:
                flags.append(f"회피({rel.get('disengagement_severity','')})")
            if r["low_reliability"]:
                flags.append(f"저신뢰(std={rel.get('std_dev_max',0):.2f})")
            if rel.get("layer_inconsistency"):
                flags.append(f"레이어불일치({rel.get('divergence_cause','')})")

            with st.expander(
                f"[{r['student_id']}] {r['created_at'][:10]}  |  "
                f"MTI={r['mti']}  {'  '.join(flags)}"):
                col_a, col_b, col_c = st.columns(3)
                if col_a.button("✅ confirm", key=f"c_{r['metric_id']}"):
                    st.success("확인 완료 (측정 유효 처리)")
                if col_b.button("🔄 remeasure", key=f"r_{r['metric_id']}"):
                    st.info("재측정은 measure_worker를 통해 실행됩니다.")
                if col_c.button("❌ reject", key=f"x_{r['metric_id']}"):
                    conn.execute(
                        "UPDATE session_metrics SET disengagement_flag=1 WHERE metric_id=?",
                        (r["metric_id"],))
                    conn.commit()
                    st.warning("측정 무효 처리됨 (시계열 제외)")
                st.json(rel)

    # ── 측정 큐 상태 ──────────────────────────────────────────────────
    st.subheader("⏳ 측정 큐 상태")
    q_rows = conn.execute("""
        SELECT mq.status, COUNT(*) as cnt
        FROM measure_queue mq
        JOIN sessions s ON s.id = mq.session_id
        WHERE s.course_id=?
        GROUP BY mq.status
    """, (course_id,)).fetchall()
    if q_rows:
        q_df = pd.DataFrame([dict(r) for r in q_rows])
        st.dataframe(q_df, hide_index=True)
    else:
        st.write("큐가 비어 있습니다.")
