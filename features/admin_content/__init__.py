"""Admin content management feature block."""
from __future__ import annotations

import streamlit as st


def render(conn, prof_id: str, course_id: str) -> None:
    st.title("평가 콘텐츠 관리")
    st.caption("Phase A 객관식 문항과 Phase B PBL 과제를 한 화면에서 관리합니다.")
