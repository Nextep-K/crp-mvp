"""
app.py — CRP MVP 메인 진입점 (09 §2)

인증 / 역할 라우팅:
  학생: 하나의 연속 플로우(Phase A → Phase B → 제출 완료 → 리포트 대기)
  교수: 대시보드 직행

원칙:
- 학생 UX는 연속 수행으로 보이게 한다.
- 측정 엔진과 저장소는 Phase A / Phase B를 분리한다.
- 엔진 함수는 st.session_state를 직접 읽지 않는다.
- v0.5.1부터 과목 라우팅은 features/course_routing 블록으로 분리한다.
- v0.5.2부터 평가 콘텐츠 관리는 features/admin_content 블록으로 분리한다.
"""
from __future__ import annotations

import os
import sys

import streamlit as st

BASE_DIR = os.path.dirname(__file__)
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "engines"))
sys.path.insert(0, os.path.join(BASE_DIR, "engines", "phase_b_engine"))
sys.path.insert(0, os.path.join(BASE_DIR, "storage"))

import db
from auth import privacy_notice
from features.course_routing import service as course_routing_service
from features.course_routing.ui import render_student_selector

st.set_page_config(page_title="CRP 인지 재구성 프로토콜", layout="wide")


@st.cache_resource
def get_db():
    conn = db.get_connection(os.path.join(BASE_DIR, "storage", "data.db"))
    db.init_schema(conn)
    db.init_question_pool_if_empty(conn, os.path.join(BASE_DIR, "config", "question_pool.json"))
    db.init_pbl_tasks_if_empty(conn, os.path.join(BASE_DIR, "config", "pbl_tasks.json"))
    course_routing_service.init_course_routing(conn)
    return conn


def _clear_flow_state() -> None:
    """로그아웃 또는 새 시작 시 UI 상태만 초기화한다. DB 저장 데이터는 유지한다."""
    for key in [
        "phase_a_questions",
        "student_flow_view",
        "flow_phase_b_started",
        "session_id",
        "session_start",
        "chat_messages",
        "current_q",
        "session_ended",
        "current_task_snapshot",
    ]:
        st.session_state.pop(key, None)


def login_page():
    st.title("CRP 시스템")
    st.subheader("로그인")

    role = st.radio("역할 선택", ["학생", "교수"], horizontal=True)
    user_id = st.text_input("사용자 ID")

    if role == "교수":
        pw = st.text_input("교수 비밀번호", type="password")
        if st.button("로그인", type="primary"):
            try:
                correct = st.secrets.get("PROF_PASSWORD", "")
            except Exception:
                correct = ""
            if correct and pw == correct and user_id:
                _clear_flow_state()
                st.session_state.update(
                    {
                        "role": "professor",
                        "user_id": user_id,
                        "course_id": "admin",
                        "logged_in": True,
                    }
                )
                st.rerun()
            else:
                st.error("비밀번호가 올바르지 않습니다. PROF_PASSWORD가 설정되어 있는지 확인하세요.")
    else:
        st.info(privacy_notice())
        conn = get_db()
        selected_course = render_student_selector(conn)
        if st.button("로그인", type="primary"):
            if not user_id:
                st.error("사용자 ID를 입력하세요.")
            elif not selected_course:
                st.error("과목을 선택하세요.")
            else:
                course_id = selected_course["course_id"]
                db.upsert_student(conn, user_id)
                db.upsert_course(
                    conn,
                    course_id,
                    name=selected_course.get("course_name", ""),
                    dept=selected_course.get("department_name", ""),
                )
                _clear_flow_state()
                st.session_state.update(
                    {
                        "role": "student",
                        "user_id": user_id,
                        "course_id": course_id,
                        "course_label": selected_course.get("course_name", course_id),
                        "logged_in": True,
                        "student_flow_view": "activity",
                    }
                )
                st.rerun()


def main():
    if not st.session_state.get("logged_in"):
        login_page()
        return

    role = st.session_state["role"]
    conn = get_db()

    with st.sidebar:
        st.write(f"**{st.session_state['user_id']}** ({role})")
        st.caption(f"과목: {st.session_state['course_id']}")
        if st.button("로그아웃"):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

        if role == "student":
            st.divider()
            st.caption("학생 화면은 Phase A → Phase B → 제출 완료 순서로 자동 진행됩니다.")
            if st.button("오늘 활동", use_container_width=True):
                st.session_state["student_flow_view"] = "activity"
                st.rerun()
            if st.button("결과 리포트", use_container_width=True):
                st.session_state["student_flow_view"] = "report"
                st.rerun()
        else:
            st.divider()
            st.caption("교수/관리자 화면")
            st.radio(
                "관리 메뉴",
                ["측정 현황", "과목 관리", "평가 콘텐츠 관리"],
                key="admin_view",
            )

    if role == "student":
        from pages._student_flow import render
        render(conn, st.session_state["user_id"], st.session_state["course_id"])
    else:
        if st.session_state.get("admin_view") == "과목 관리":
            from features.course_routing.ui import render_admin as render
        elif st.session_state.get("admin_view") == "평가 콘텐츠 관리":
            from features.admin_content import render
        else:
            from pages._dashboard import render
        render(conn, st.session_state["user_id"], st.session_state["course_id"])


main()
