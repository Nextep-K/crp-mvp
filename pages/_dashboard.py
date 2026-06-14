"""
pages/_dashboard.py — 교수 대시보드 (06 §2~3, 09 §6)

v0.5.5-demo-flow-check:
- 교수 로그인 course_id가 "admin"으로 고정되어도 실제 학생 세션을 볼 수 있도록 과목 범위를 선택한다.
- 측정 결과가 아직 없어도 제출 세션과 measure_queue 상태를 과목 범위 기준으로 보여준다.
- 대학 시연 시 "학생 제출 → 교수 화면 확인" 흐름이 빈 화면으로 끊기지 않게 한다.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

import pandas as pd
import streamlit as st


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return {}


def _load_course_options(conn) -> list[dict[str, Any]]:
    """Return dashboard course scope options. First option is all courses."""
    options: list[dict[str, Any]] = [
        {
            "label": "전체 과목",
            "course_id": None,
            "course_name": "전체 과목",
        }
    ]

    seen: set[str] = set()
    try:
        from features.course_routing import repository as course_repository

        routes = course_repository.list_course_routes(conn, active_only=False)
        for route in routes:
            cid = route.get("course_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            status = "활성" if route.get("active") else "비활성"
            options.append(
                {
                    "label": f"{cid} — {route.get('course_name', '')} ({status})",
                    "course_id": cid,
                    "course_name": route.get("course_name", ""),
                }
            )
    except Exception:
        pass

    try:
        rows = conn.execute("SELECT id, name FROM courses ORDER BY id").fetchall()
        for row in rows:
            cid = row["id"]
            if not cid or cid in seen:
                continue
            seen.add(cid)
            options.append(
                {
                    "label": f"{cid} — {row['name'] or ''}",
                    "course_id": cid,
                    "course_name": row["name"] or "",
                }
            )
    except Exception:
        pass

    return options


def _select_course_scope(conn, incoming_course_id: str) -> dict[str, Any]:
    options = _load_course_options(conn)
    default_index = 0
    if incoming_course_id and incoming_course_id != "admin":
        for idx, option in enumerate(options):
            if option.get("course_id") == incoming_course_id:
                default_index = idx
                break

    selected_label = st.selectbox(
        "조회 과목 범위",
        [option["label"] for option in options],
        index=default_index,
        key="dashboard_course_scope",
    )
    selected = options[[option["label"] for option in options].index(selected_label)]

    if selected.get("course_id"):
        st.caption(f"현재 조회 범위: {selected['course_id']} · {selected.get('course_name') or '-'}")
    else:
        st.caption("현재 조회 범위: 전체 과목")
    return selected


def _where_for_course(alias: str, course_id: str | None) -> tuple[str, list[Any]]:
    if not course_id:
        return "", []
    return f"WHERE {alias}.course_id=?", [course_id]


def _render_recent_sessions(conn, course_id: str | None) -> None:
    st.subheader("최근 학생 제출 / 세션 상태")
    where_sql, params = _where_for_course("s", course_id)
    rows = conn.execute(
        f"""
        SELECT
            s.course_id,
            COALESCE(c.name, '') AS course_name,
            s.student_id,
            s.id AS session_id,
            s.task_id,
            s.status,
            s.session_start,
            s.session_end,
            s.created_at
        FROM sessions s
        LEFT JOIN courses c ON c.id = s.course_id
        {where_sql}
        ORDER BY COALESCE(s.session_end, s.session_start, s.created_at) DESC
        LIMIT 30
        """,
        params,
    ).fetchall()

    if not rows:
        st.write("아직 제출되었거나 진행 중인 학생 세션이 없습니다.")
        return

    df = pd.DataFrame([dict(r) for r in rows])
    df = df[
        [
            "course_id",
            "course_name",
            "student_id",
            "session_id",
            "task_id",
            "status",
            "session_start",
            "session_end",
        ]
    ]
    df.columns = ["과목 ID", "과목명", "학생", "세션 ID", "과제 ID", "상태", "시작", "종료"]
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption("측정 결과가 아직 없어도 이 표에 pending_measure 세션이 보이면 학생 제출은 완료된 상태입니다.")


def _render_measure_queue(conn, course_id: str | None) -> None:
    st.subheader("⏳ 측정 큐 상태")

    where_sql, params = _where_for_course("s", course_id)
    q_rows = conn.execute(
        f"""
        SELECT
            s.course_id,
            COALESCE(c.name, '') AS course_name,
            mq.status,
            COUNT(*) AS cnt
        FROM measure_queue mq
        JOIN sessions s ON s.id = mq.session_id
        LEFT JOIN courses c ON c.id = s.course_id
        {where_sql}
        GROUP BY s.course_id, c.name, mq.status
        ORDER BY s.course_id, mq.status
        """,
        params,
    ).fetchall()

    if q_rows:
        q_df = pd.DataFrame([dict(r) for r in q_rows])
        q_df.columns = ["과목 ID", "과목명", "큐 상태", "건수"]
        st.dataframe(q_df, use_container_width=True, hide_index=True)
    else:
        st.write("큐가 비어 있습니다.")

    pending = conn.execute(
        f"""
        SELECT
            mq.job_id,
            mq.status,
            s.course_id,
            COALESCE(c.name, '') AS course_name,
            s.student_id,
            s.id AS session_id,
            s.status AS session_status,
            s.session_start,
            s.session_end,
            mq.created_at
        FROM measure_queue mq
        JOIN sessions s ON s.id = mq.session_id
        LEFT JOIN courses c ON c.id = s.course_id
        {where_sql}
        ORDER BY mq.created_at DESC
        LIMIT 30
        """,
        params,
    ).fetchall()

    if pending:
        with st.expander("큐 상세 보기", expanded=False):
            p_df = pd.DataFrame([dict(r) for r in pending])
            p_df.columns = [
                "작업 ID",
                "큐 상태",
                "과목 ID",
                "과목명",
                "학생",
                "세션 ID",
                "세션 상태",
                "시작",
                "종료",
                "큐 등록",
            ]
            st.dataframe(p_df, use_container_width=True, hide_index=True)


def _load_metric_rows(conn, course_id: str | None):
    where_sql, params = _where_for_course("sm", course_id)
    return conn.execute(
        f"""
        SELECT
            sm.student_id,
            sm.course_id,
            COALESCE(c.name, '') AS course_name,
            sm.mti,
            sm.qli,
            sm.rec,
            sm.recon,
            sm.orc,
            sm.qualitative_band_mti,
            sm.disengagement_flag,
            sm.low_reliability,
            sm.rubric_version,
            sm.created_at,
            sm.metric_id,
            sm.crp_output
        FROM session_metrics sm
        LEFT JOIN courses c ON c.id = sm.course_id
        {where_sql}
        ORDER BY sm.created_at DESC
        """,
        params,
    ).fetchall()


def _render_summary_metrics(df: pd.DataFrame, rows: list[Any]) -> None:
    st.subheader("측정 현황 요약")
    c1, c2, c3, c4 = st.columns(4)

    c1.metric("측정 결과", len(df))
    c2.metric("측정 회피 탐지", int(df["disengagement_flag"].fillna(0).sum()))
    c3.metric("신뢰도 낮음", int(df["low_reliability"].fillna(0).sum()))

    grok_count = 0
    for row in rows:
        out = _safe_json_loads(row["crp_output"])
        if out.get("grokking", {}).get("detected"):
            grok_count += 1
    c4.metric("Grokking 탐지", grok_count)


def _render_timeline(conn, df: pd.DataFrame) -> None:
    st.subheader("학생별 MTI 시계열")

    df = df.copy()
    df["student_scope"] = df["student_id"] + " / " + df["course_id"]
    scope_pairs = (
        df[["student_scope", "student_id", "course_id"]]
        .drop_duplicates()
        .sort_values("student_scope")
        .to_dict("records")
    )
    labels = [p["student_scope"] for p in scope_pairs]
    selected = st.multiselect("학생·과목 선택", labels, default=labels[:5])

    if not selected:
        return

    pair_map = {p["student_scope"]: (p["student_id"], p["course_id"]) for p in scope_pairs}
    timeline = {}
    for label in selected:
        sid, cid = pair_map[label]
        s_rows = conn.execute(
            """
            SELECT mti, qli, created_at
            FROM session_metrics
            WHERE course_id=? AND student_id=? AND disengagement_flag=0
            ORDER BY created_at ASC
            """,
            (cid, sid),
        ).fetchall()
        if s_rows:
            timeline[label] = [r["mti"] for r in s_rows]

    if timeline:
        max_len = max(len(v) for v in timeline.values())
        padded = {k: v + [None] * (max_len - len(v)) for k, v in timeline.items()}
        st.line_chart(pd.DataFrame(padded), height=260)


def _render_flagged_sessions(conn, course_id: str | None) -> None:
    st.subheader("🚩 신뢰도 플래그 세션")

    and_sql, params = ("", [])
    if course_id:
        and_sql, params = ("AND course_id=?", [course_id])
    flag_rows = conn.execute(
        f"""
        SELECT metric_id, student_id, course_id, mti, qli, disengagement_flag,
               low_reliability, created_at, crp_output
        FROM session_metrics
        WHERE (disengagement_flag=1 OR low_reliability=1)
        {and_sql}
        ORDER BY created_at DESC
        """,
        params,
    ).fetchall()

    if not flag_rows:
        st.write("현재 플래그 세션이 없습니다.")
        return

    for row in flag_rows:
        out = _safe_json_loads(row["crp_output"])
        rel = out.get("reliability", {})
        flags = []
        if row["disengagement_flag"]:
            flags.append(f"회피({rel.get('disengagement_severity', '')})")
        if row["low_reliability"]:
            flags.append(f"저신뢰(std={rel.get('std_dev_max', 0):.2f})")
        if rel.get("layer_inconsistency"):
            flags.append(f"레이어불일치({rel.get('divergence_cause', '')})")

        with st.expander(
            f"[{row['course_id']} / {row['student_id']}] {row['created_at'][:10]}  |  "
            f"MTI={row['mti']}  {'  '.join(flags)}"
        ):
            col_a, col_b, col_c = st.columns(3)
            if col_a.button("✅ confirm", key=f"c_{row['metric_id']}"):
                st.success("확인 완료 (측정 유효 처리)")
            if col_b.button("🔄 remeasure", key=f"r_{row['metric_id']}"):
                st.info("재측정은 measure_worker를 통해 실행됩니다.")
            if col_c.button("❌ reject", key=f"x_{row['metric_id']}"):
                conn.execute(
                    "UPDATE session_metrics SET disengagement_flag=1 WHERE metric_id=?",
                    (row["metric_id"],),
                )
                conn.commit()
                st.warning("측정 무효 처리됨 (시계열 제외)")
            st.json(rel)


def render(conn, prof_id: str, course_id: str):
    st.title("교수 대시보드")
    st.caption("대학 시연용 확인 화면: 학생 제출 상태, 측정 큐, 측정 결과를 같은 흐름에서 확인합니다.")

    selected_scope = _select_course_scope(conn, course_id)
    selected_course_id = selected_scope.get("course_id")

    rows = _load_metric_rows(conn, selected_course_id)

    if not rows:
        st.info("아직 측정 완료 결과가 없습니다. 학생 제출 여부와 측정 큐 상태를 먼저 확인하세요.")
        _render_recent_sessions(conn, selected_course_id)
        _render_measure_queue(conn, selected_course_id)
        return

    df = pd.DataFrame([dict(r) for r in rows])

    _render_summary_metrics(df, rows)

    st.subheader("최근 측정 결과")
    result_df = df[
        [
            "course_id",
            "course_name",
            "student_id",
            "mti",
            "qli",
            "rec",
            "recon",
            "orc",
            "qualitative_band_mti",
            "disengagement_flag",
            "low_reliability",
            "created_at",
        ]
    ].copy()
    result_df.columns = [
        "과목 ID",
        "과목명",
        "학생",
        "MTI",
        "QLI",
        "Rec",
        "Recon",
        "Orc",
        "MTI 구간",
        "회피",
        "저신뢰",
        "측정 완료",
    ]
    st.dataframe(result_df, use_container_width=True, hide_index=True)

    _render_timeline(conn, df)
    _render_flagged_sessions(conn, selected_course_id)
    _render_recent_sessions(conn, selected_course_id)
    _render_measure_queue(conn, selected_course_id)
