"""Admin evaluation content management UI.

This module groups the Phase A objective-question pool and the Phase B PBL task
pool under one administrator branch. The underlying CRUD implementation remains
in pages._question_pool so v0.5 data behavior is unchanged.
"""
from __future__ import annotations

import streamlit as st

from pages._question_pool import _render_phase_a, _render_phase_b


def render(conn, prof_id: str, course_id: str) -> None:
    """Render the administrator content-management screen."""
    st.title("평가 콘텐츠 관리")
    st.caption("Phase A 객관식 문항과 Phase B PBL 과제를 한 화면에서 관리합니다.")
    st.info("삭제 대신 비활성화를 사용합니다. 이미 제출된 세션의 문항/과제 스냅샷은 유지됩니다.")

    tab_a, tab_b = st.tabs(["Phase A 객관식 문항 관리", "Phase B PBL 과제 관리"])
    with tab_a:
        _render_phase_a(conn, prof_id)
    with tab_b:
        _render_phase_b(conn, prof_id)
