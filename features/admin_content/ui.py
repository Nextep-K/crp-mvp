"""Administrator UI for Phase A and Phase B content management.

The top of each screen shows what students will actually see at the current
configuration state. CRUD controls remain in pages._question_pool so the v0.5
storage behavior is unchanged.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

import db
from features.course_routing import repository as course_repository
from pages._question_pool import _render_phase_a, _render_phase_b


PHASE_A_LABEL = "Phase A — 객관식 문항 관리"
PHASE_B_LABEL = "Phase B — PBL 과제 관리"


def _active_label(value) -> str:
    return "활성" if value else "비활성"


def _render_phase_a_current_preview(conn) -> None:
    st.markdown("### 현재 학생에게 노출되는 Phase A 객관식 문항")
    st.caption(
        "Phase A는 전 과목 공통입니다. 학생 로그인 후 사전 체크에서 현재 활성 문항 풀이 사용됩니다."
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
        f"**ID:** {task['task_id']} · "
        f"**난이도:** {task.get('difficulty') or 'mid'} · "
        f"**버전:** {task.get('task_version') or '-'} · "
        f"**목표지표:** {metrics} · "
        f"**트리거:** {triggers}"
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


def _render_phase_b_current_preview(conn) -> None:
    st.markdown("### 현재 학생에게 노출되는 Phase B PBL 과제")
    st.caption(
        "Phase B는 과목별로 배정됩니다. 아래 과목을 선택하면 학생이 해당 과목으로 로그인했을 때 시작되는 과제를 확인할 수 있습니다."
    )

    courses = course_repository.list_course_routes(conn, active_only=False)
    if not courses:
        st.error("등록된 과목이 없습니다. 먼저 과목 관리에서 과목을 등록하세요.")
        return

    course_options = {
        f"{c['course_id']} — {c['course_name']} ({_active_label(c.get('active'))})": c
        for c in courses
    }
    selected_label = st.selectbox(
        "현재 과목 선택",
        list(course_options.keys()),
        key="phase_b_admin_preview_course",
    )
    selected_course = course_options[selected_label]
    selected_course_id = selected_course["course_id"]

    assigned_tasks = course_repository.get_active_pbl_tasks_for_course(conn, selected_course_id)
    using_fallback = False
    tasks = assigned_tasks
    if not tasks:
        using_fallback = True
        tasks = db.get_active_pbl_tasks(conn)

    st.write(
        f"**선택 과목:** {selected_course_id} · "
        f"{selected_course.get('college_name', '')} / {selected_course.get('department_name', '')} / {selected_course.get('course_name', '')}"
    )

    if assigned_tasks:
        st.success("이 과목에 직접 연결된 활성 PBL 과제가 있습니다.")
    elif tasks:
        st.warning(
            "이 과목에 직접 연결된 활성 PBL 과제가 없습니다. 현재 학생 화면은 공통 활성 PBL 과제 풀로 fallback합니다."
        )
        st.caption("과목별 지정 출제를 원하면 과목 관리 → 과목별 PBL 연결에서 연결을 설정하세요.")
    else:
        st.error("활성화된 PBL 과제가 없습니다. 아래 관리 도구에서 과제를 등록·활성화하세요.")
        return

    primary_task = tasks[0]
    _render_task_preview(
        primary_task,
        title_prefix="현재 학생 세션 시작 시 출제되는 과제" if not using_fallback else "현재 fallback으로 출제되는 과제",
    )

    if len(tasks) > 1:
        st.markdown("#### 같은 조건에서 사용 가능한 추가 활성 과제")
        rows = []
        for idx, task in enumerate(tasks[1:], 2):
            rows.append({
                "순서": idx,
                "ID": task["task_id"],
                "제목": task["title"],
                "난이도": task.get("difficulty") or "mid",
                "기본문항": len(task.get("questions") or []),
                "버전": task.get("task_version") or "-",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption("현재 학생 세션은 목록의 첫 번째 과제로 시작합니다. 순서 로직은 Phase B 세션 선택 규칙을 따릅니다.")


def render(conn, prof_id: str, course_id: str) -> None:
    """Legacy grouped content-management screen kept for compatibility."""
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
        render_phase_a_admin(conn, prof_id, course_id)
    else:
        render_phase_b_admin(conn, prof_id, course_id)


def render_phase_a_admin(conn, prof_id: str, course_id: str) -> None:
    st.title("Phase A 관리")
    st.caption("객관식 사전 진단 문항을 관리합니다. Phase A는 모든 과목에 공통 적용됩니다.")
    st.info("상단에는 현재 학생에게 노출되는 활성 문항 풀이 먼저 표시됩니다.")

    _render_phase_a_current_preview(conn)
    st.divider()
    st.markdown("## Phase A 문항 추가 / 수정 / 활성화")
    _render_phase_a(conn, prof_id)


def render_phase_b_admin(conn, prof_id: str, course_id: str) -> None:
    st.title("Phase B 관리")
    st.caption("과목별 PBL 과제를 관리합니다. Phase B는 과목 라우팅과 연결됩니다.")
    st.info("상단에는 선택 과목으로 학생이 로그인했을 때 실제로 시작되는 PBL 과제가 먼저 표시됩니다.")

    _render_phase_b_current_preview(conn)
    st.divider()
    st.markdown("## Phase B PBL 과제 추가 / 수정 / 활성화")
    _render_phase_b(conn, prof_id)
