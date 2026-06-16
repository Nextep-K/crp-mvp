"""Administrator UI for Phase A and Phase B content management.

v0.5.4-demo keeps the professor/admin screens presentation-friendly for
university pilot demos: current student-facing content is shown first, while
advanced CRUD tools remain available only in collapsed sections.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db
from features.course_routing import repository as course_repository
from features.course_routing import service as course_service
from pages._question_pool import _render_phase_a, _render_phase_b


PHASE_A_LABEL = "Phase A — 객관식 문항 관리"
PHASE_B_LABEL = "Phase B — PBL 과제 관리"


def _active_label(value) -> str:
    return "활성" if value else "비활성"


def _task_label(task: dict) -> str:
    return f"{task['task_id']} — {task['title']}"


def _index_by_course_id(courses: list[dict], course_id: str | None) -> int:
    if not course_id:
        return 0
    for idx, course in enumerate(courses):
        if course.get("course_id") == course_id:
            return idx
    return 0


def _render_phase_a_current_preview(conn) -> None:
    st.markdown("### 현재 학생에게 노출되는 Phase A 객관식 문항")
    st.caption(
        "Phase A는 전 과목 공통 사전 진단입니다. 학생 로그인 후 현재 활성 문항 풀이 사용됩니다."
    )

    constraints = db.check_pool_constraints(conn)
    c1, c2, c3 = st.columns(3)
    c1.metric("문항 풀 버전", db.get_pool_version(conn))
    c2.metric("QLI 활성 문항", constraints["qli_active"])
    c3.metric("MTI 활성 문항", constraints["mti_active"])

    if constraints["phase_a_ready"]:
        st.success("현재 Phase A 진단 가능 상태입니다. QLI/MTI 활성 문항이 각각 5개 이상입니다.")
    for warning in constraints["warnings"]:
        st.warning(warning)

    active_items = db.get_active_items(conn)
    if not active_items:
        st.error("현재 활성화된 Phase A 문항이 없습니다.")
        return

    preview = pd.DataFrame(active_items)
    preview = preview[["item_id", "axis", "text", "reverse", "sub_domain", "difficulty", "pool_version"]].copy()
    preview.columns = ["ID", "축", "문항", "역문항", "하위영역", "난이도", "버전"]
    preview["역문항"] = preview["역문항"].map({1: "예", 0: "아니오", True: "예", False: "아니오"})
    st.dataframe(preview, use_container_width=True, hide_index=True)
    st.caption("학생 화면에서는 이 활성 문항 풀에서 QLI 5개 + MTI 5개가 균형 추출됩니다.")


def _format_task_meta(task: dict) -> str:
    metrics = ", ".join(task.get("target_metrics") or []) or "-"
    triggers = ", ".join(task.get("trigger_design") or []) or "-"
    return (
        f"ID: {task['task_id']} · "
        f"난이도: {task.get('difficulty') or 'mid'} · "
        f"버전: {task.get('task_version') or '-'} · "
        f"목표지표: {metrics} · "
        f"트리거: {triggers}"
    )


def _render_task_preview(task: dict, *, title_prefix: str = "현재 학생 세션 시작 시 출제되는 과제") -> None:
    st.markdown(f"#### {title_prefix}")
    st.write(f"**{task['title']}**")
    st.caption(_format_task_meta(task))

    st.markdown("**기본 문항**")
    for i, question in enumerate(task.get("questions") or [], 1):
        st.write(f"{i}. {question}")

    advanced = task.get("advanced_questions") or []
    if advanced:
        with st.expander("심화 문항 보기", expanded=False):
            for i, question in enumerate(advanced, 1):
                st.write(f"심화 {i}. {question}")


def _select_phase_b_course(conn) -> dict | None:
    courses = course_repository.list_course_routes(conn, active_only=False)
    if not courses:
        st.error("등록된 과목이 없습니다. 먼저 과목 관리에서 과목을 등록하세요.")
        return None

    default_index = _index_by_course_id(courses, course_service.DEFAULT_DEMO_COURSE_ID)
    labels = [
        f"{c['course_id']} — {c['course_name']} ({_active_label(c.get('active'))})"
        for c in courses
    ]
    selected_label = st.selectbox(
        "시연 과목 선택",
        labels,
        index=default_index,
        key="phase_b_demo_course",
    )
    return courses[labels.index(selected_label)]


def _render_phase_b_current_preview(conn, selected_course: dict) -> None:
    st.markdown("### 현재 학생에게 노출되는 Phase B PBL 과제")
    st.caption("아래 내용은 선택 과목으로 학생이 로그인했을 때 실제로 시작되는 PBL 과제입니다.")

    selected_course_id = selected_course["course_id"]
    assigned_tasks = course_repository.get_active_pbl_tasks_for_course(conn, selected_course_id)
    using_fallback = False
    tasks = assigned_tasks
    if not tasks:
        using_fallback = True
        tasks = db.get_active_pbl_tasks(conn)

    c1, c2 = st.columns([2, 1])
    c1.write(
        f"**선택 과목:** {selected_course_id} · "
        f"{selected_course.get('college_name', '')} / {selected_course.get('department_name', '')} / {selected_course.get('course_name', '')}"
    )
    c2.metric("출제 방식", "과목 연결" if assigned_tasks else "공통 fallback")

    if assigned_tasks:
        st.success("이 과목에 직접 연결된 활성 PBL 과제가 학생에게 출제됩니다.")
    elif tasks:
        st.warning("이 과목에 직접 연결된 활성 PBL 과제가 없어 공통 활성 과제 풀이 사용됩니다.")
    else:
        st.error("활성화된 PBL 과제가 없습니다. 고급 관리 기능에서 과제를 등록·활성화하세요.")
        return

    _render_task_preview(
        tasks[0],
        title_prefix="현재 학생 세션 시작 시 출제되는 과제" if not using_fallback else "현재 fallback으로 출제되는 과제",
    )


def _render_phase_b_demo_selector(conn, selected_course: dict) -> None:
    st.markdown("### 시연용 과제 선택")
    st.caption(
        "대학 시연에서는 복잡한 편집 기능보다, 어떤 PBL 과제가 학생에게 노출되는지 빠르게 선택하는 흐름만 보여줍니다."
    )

    tasks = db.get_active_pbl_tasks(conn)
    if not tasks:
        st.info("선택 가능한 활성 PBL 과제가 없습니다.")
        return

    task_options = {_task_label(task): task for task in tasks}
    selected_task_label = st.selectbox(
        "학생에게 노출할 PBL 과제",
        list(task_options.keys()),
        key="phase_b_demo_task",
    )
    selected_task = task_options[selected_task_label]

    with st.expander("선택한 과제 미리보기", expanded=False):
        _render_task_preview(selected_task, title_prefix="선택 후보 과제")

    if st.button("이 과제를 현재 과목의 시연용 과제로 설정", type="primary"):
        course_id = selected_course["course_id"]
        conn.execute(
            "UPDATE course_task_routes SET active=0, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE course_id=?",
            (course_id,),
        )
        conn.commit()
        course_repository.set_course_task_route(conn, course_id, selected_task["task_id"], active=True)
        st.success("시연용 Phase B 과제가 설정되었습니다.")
        st.rerun()


def render(conn, prof_id: str, course_id: str) -> None:
    """Legacy grouped content-management screen kept for compatibility."""
    st.title("평가 콘텐츠 관리")
    st.caption("Phase A 객관식 문항과 Phase B PBL 과제를 한 화면에서 관리합니다.")
    st.info("대학 시연용 MVP에서는 Phase A 관리 / Phase B 관리 메뉴를 직접 사용하는 것을 권장합니다.")

    section = st.radio(
        "관리할 콘텐츠 선택",
        [PHASE_A_LABEL, PHASE_B_LABEL],
        horizontal=True,
        key="admin_content_section",
    )

    st.divider()

    if section == PHASE_A_LABEL:
        render_phase_a_admin(conn, prof_id, course_id)
    else:
        render_phase_b_admin(conn, prof_id, course_id)


def render_phase_a_admin(conn, prof_id: str, course_id: str) -> None:
    st.title("Phase A 관리")
    st.caption("객관식 사전 진단 문항을 확인합니다. Phase A는 모든 과목에 공통 적용됩니다.")
    st.info("대학 시연용 화면에서는 현재 학생에게 노출되는 문항 확인을 우선합니다.")

    _render_phase_a_current_preview(conn)

    with st.expander("고급 문항 추가 / 수정 / 활성화 기능", expanded=False):
        st.caption("파일럿 시연에서는 접어 두는 운영자용 기능입니다.")
        _render_phase_a(conn, prof_id)


def render_phase_b_admin(conn, prof_id: str, course_id: str) -> None:
    st.title("Phase B 관리")
    st.caption("학생 AI 대화 세션에 사용되는 PBL 과제를 확인하고, 시연용 과제를 선택합니다.")
    st.info("대학 시연용 MVP에서는 현재 출제 과제 확인과 시연용 과제 선택만 전면에 노출합니다.")

    selected_course = _select_phase_b_course(conn)
    if not selected_course:
        return

    _render_phase_b_current_preview(conn, selected_course)
    st.divider()
    _render_phase_b_demo_selector(conn, selected_course)

    with st.expander("고급 PBL 과제 편집 / 활성화 기능", expanded=False):
        st.caption("과제 생성·상세 수정·활성/비활성 조작은 파일럿 시연 화면에서는 접어 둡니다.")
        _render_phase_b(conn, prof_id)
