"""Admin evaluation content management UI.

This module groups the Phase A objective-question pool and the Phase B PBL task
pool under one administrator branch. The underlying CRUD implementation remains
in pages._question_pool so v0.5 data behavior is unchanged.
"""
from __future__ import annotations

import streamlit as st

from pages._question_pool import _render_phase_a, _render_phase_b


PHASE_A_LABEL = "Phase A — 객관식 문항 관리"
PHASE_B_LABEL = "Phase B — PBL 과제 관리"


def render(conn, prof_id: str, course_id: str) -> None:
    """Render the administrator content-management screen."""
    st.title("평가 콘텐츠 관리")
    st.caption("Phase A 객관식 문항과 Phase B PBL 과제를 한 화면에서 관리합니다.")
    st.info("삭제 대신 비활성화를 사용합니다. 이미 제출된 세션의 문항/과제 스냅샷은 유지됩니다.")

    section = st.radio(
        "관리할 콘텐츠 선택",
        [PHASE_A_LABEL, PHASE_B_LABEL],
        horizontal=True,
        key="admin_content_section",
    )

    st.divider()

    if section == PHASE_A_LABEL:
        st.markdown("## Phase A — 객관식 문항 관리")
        st.caption("공통 사전 진단 문항입니다. 과목별로 달라지지 않습니다.")
        _render_phase_a(conn, prof_id)
    else:
        st.markdown("## Phase B — PBL 과제 관리")
        st.caption("과목별로 배정되는 주관식·대화형 PBL 과제입니다.")
        _render_phase_b(conn, prof_id)
