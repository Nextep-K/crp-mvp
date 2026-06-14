"""Streamlit UI for course routing."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from . import repository, service


def _course_label(route: dict) -> str:
    return f"{route['subject_code']} - {route['course_name']}"


def render_student_selector(conn) -> dict | None:
    """Render student course selector and return selected route."""
    service.init_course_routing(conn)
    colleges = repository.list_colleges(conn)
    if not colleges:
        st.error("활성화된 과목이 없습니다. 관리자에게 문의하세요.")
        return None

    college_labels = [f"{c['college_code']}. {c['college_name']}" for c in colleges]
    selected_college_label = st.selectbox("단과대학 선택", college_labels)
    selected_college = colleges[college_labels.index(selected_college_label)]

    departments = repository.list_departments(conn, selected_college["college_code"])
    if not departments:
        st.error("선택한 단과대학에 활성화된 학과가 없습니다.")
        return None

    department_labels = [f"{d['department_code']}. {d['department_name']}" for d in departments]
    selected_department_label = st.selectbox("학과 선택", department_labels)
    selected_department = departments[department_labels.index(selected_department_label)]

    courses = repository.list_courses(
        conn,
        selected_college["college_code"],
        selected_department["department_code"],
    )
    if not courses:
        st.error("선택한 학과에 활성화된 과목이 없습니다.")
        return None

    course_labels = [_course_label(c) for c in courses]
    selected_course_label = st.selectbox("과목 선택", course_labels)
    selected_course = courses[course_labels.index(selected_course_label)]
    st.caption(f"선택 과목 코드: {selected_course['course_id']}")
    return selected_course


def render_admin(conn, prof_id: str, course_id: str) -> None:
    """Render simplified course management screen for university demo."""
    service.init_course_routing(conn)
    st.title("과목 관리")
    st.caption("대학 시연용 MVP 화면: 과목 현황을 먼저 확인하고, 수정 기능은 고급 설정에 둡니다.")
    st.info("Phase A 객관식 문항 풀은 전 과목 공통입니다. 과목별로는 Phase B PBL 과제만 연결됩니다.")

    routes = repository.list_course_routes(conn, active_only=False)
    task_routes = repository.list_course_task_routes(conn)
    tasks = _get_all_pbl_tasks(conn)

    _render_course_overview(routes, task_routes)
    _render_course_summary_table(routes, task_routes, tasks)
    _render_demo_course_preview(routes, task_routes, tasks, course_id)

    st.divider()
    with st.expander("고급 설정: 과목 추가 / 수정 / 활성화", expanded=False):
        st.caption("시연 중에는 보통 사용하지 않습니다. 과목 코드를 추가하거나 노출 상태를 바꿀 때만 펼쳐서 사용합니다.")
        _render_course_routes(conn)

    with st.expander("고급 설정: 과목별 Phase B PBL 과제 연결", expanded=False):
        st.caption("특정 과목에 별도 PBL 과제를 연결할 때만 사용합니다. 연결된 과제가 없으면 공통 활성 PBL 과제가 사용됩니다.")
        _render_course_task_routes(conn)


def _render_course_overview(routes: list[dict], task_routes: list[dict]) -> None:
    st.markdown("### 현재 등록된 과목 현황")
    active_routes = [r for r in routes if r.get("active")]
    active_task_course_ids = {
        r.get("course_id") for r in task_routes if r.get("active")
    }
    active_connected = [r for r in active_routes if r.get("course_id") in active_task_course_ids]
    active_unconnected = [r for r in active_routes if r.get("course_id") not in active_task_course_ids]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("등록 과목", len(routes))
    c2.metric("활성 과목", len(active_routes))
    c3.metric("PBL 연결 과목", len(active_connected))
    c4.metric("미연결 활성 과목", len(active_unconnected))

    st.caption(
        "미연결 활성 과목은 과목 전용 PBL 과제가 없다는 뜻입니다. 이 경우 학생 화면에서는 공통 활성 PBL 과제가 사용됩니다."
    )


def _render_course_summary_table(routes: list[dict], task_routes: list[dict], tasks: list[dict]) -> None:
    st.markdown("### 과목 목록 요약")
    if not routes:
        st.info("등록된 과목이 없습니다.")
        return

    task_map = {str(t.get("task_id")): t for t in tasks}
    active_task_ids_by_course: dict[str, list[str]] = {}
    for route in task_routes:
        if not route.get("active"):
            continue
        active_task_ids_by_course.setdefault(route.get("course_id"), []).append(str(route.get("task_id")))

    rows = []
    for r in routes:
        task_ids = active_task_ids_by_course.get(r["course_id"], [])
        task_titles = [task_map.get(tid, {}).get("title") or tid for tid in task_ids]
        rows.append({
            "과목 ID": r["course_id"],
            "단과대학": f"{r['college_code']}. {r['college_name']}",
            "학과": f"{r['department_code']}. {r['department_name']}",
            "과목명": r["course_name"],
            "담당": r.get("professor_name") or "-",
            "Phase B 과제": ", ".join(task_titles) if task_titles else "공통 과제 사용",
            "상태": "활성" if r.get("active") else "비활성",
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_demo_course_preview(
    routes: list[dict],
    task_routes: list[dict],
    tasks: list[dict],
    current_course_id: str,
) -> None:
    st.markdown("### 현재 시연 과목 확인")
    if not routes:
        st.info("등록된 과목이 없어 시연 과목을 표시할 수 없습니다.")
        return

    active_routes = [r for r in routes if r.get("active")]
    selectable_routes = active_routes or routes
    default_index = 0
    for idx, route in enumerate(selectable_routes):
        if route.get("course_id") == current_course_id:
            default_index = idx
            break

    labels = [f"{r['course_id']} / {r['course_name']}" for r in selectable_routes]
    selected_label = st.selectbox("시연 기준 과목", labels, index=default_index, key="course_demo_preview")
    selected_route = selectable_routes[labels.index(selected_label)]

    st.write(f"**학생 선택 화면 기준 과목:** {selected_route['course_id']} — {selected_route['course_name']}")
    st.caption(
        f"{selected_route['college_name']} / {selected_route['department_name']} · 담당: {selected_route.get('professor_name') or '-'}"
    )

    connected_task_ids = [
        str(r.get("task_id"))
        for r in task_routes
        if r.get("course_id") == selected_route["course_id"] and r.get("active")
    ]
    task_map = {str(t.get("task_id")): t for t in tasks}
    connected_tasks = [task_map[tid] for tid in connected_task_ids if tid in task_map]

    if connected_tasks:
        st.success("이 과목에는 전용 Phase B PBL 과제가 연결되어 있습니다.")
        for task in connected_tasks[:3]:
            st.markdown(f"- **{task.get('title') or task.get('task_id')}**")
    else:
        fallback_tasks = [t for t in tasks if t.get("active", True)]
        st.warning("이 과목에는 전용 PBL 과제가 없습니다. 학생 화면에서는 공통 활성 PBL 과제가 사용됩니다.")
        if fallback_tasks:
            st.markdown("**공통 fallback 후보**")
            for task in fallback_tasks[:3]:
                st.markdown(f"- {task.get('title') or task.get('task_id')}")
        else:
            st.info("현재 사용할 수 있는 공통 PBL 과제도 없습니다. Phase B 관리에서 시연용 과제를 확인하세요.")


def _render_course_routes(conn) -> None:
    routes = repository.list_course_routes(conn, active_only=False)
    st.markdown("### 과목 라우팅 목록")
    if routes:
        df = pd.DataFrame([{
            "course_id": r["course_id"],
            "단과대학": f"{r['college_code']}. {r['college_name']}",
            "학과": f"{r['department_code']}. {r['department_name']}",
            "과목": f"{r['subject_code']} - {r['course_name']}",
            "담당": r.get("professor_name") or "",
            "상태": "활성" if r.get("active") else "비활성",
        } for r in routes])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("등록된 과목이 없습니다.")

    st.markdown("### 과목 추가 / 수정")
    with st.form("v051_course_route_form"):
        col1, col2, col3 = st.columns(3)
        college_code = col1.text_input("단과대학 코드", placeholder="A~Z", max_chars=1).upper()
        department_code = col2.text_input("학과 코드", placeholder="00~99", max_chars=2)
        subject_code = col3.text_input("과목 코드", placeholder="6자리 영문+숫자", max_chars=6).upper()

        college_name = st.text_input("단과대학명", placeholder="예: 인문대학")
        department_name = st.text_input("학과명", placeholder="예: 역사학과")
        course_name = st.text_input("과목명", placeholder="예: AI와 역사적 사고")
        professor_name = st.text_input("담당 교수명", placeholder="선택 입력")
        active = st.checkbox("학생 선택 화면에 노출", value=True)
        submitted = st.form_submit_button("과목 저장", type="primary")
        if submitted:
            ok, result = service.save_course_route(conn, {
                "college_code": college_code,
                "college_name": college_name,
                "department_code": department_code,
                "department_name": department_name,
                "subject_code": subject_code,
                "course_name": course_name,
                "professor_name": professor_name,
                "active": active,
            })
            if ok:
                st.success(f"과목 라우팅이 저장되었습니다: {result}")
                st.rerun()
            else:
                st.error(result)

    if routes:
        st.markdown("### 활성화 / 비활성화")
        ids = [r["course_id"] for r in routes]
        selected_id = st.selectbox("대상 과목", ids, key="v051_route_selected")
        selected = next(r for r in routes if r["course_id"] == selected_id)
        st.write(f"**{selected['course_id']}** - {selected['course_name']}")
        c1, c2 = st.columns(2)
        if selected.get("active"):
            if c1.button("비활성화", key="v051_route_off"):
                repository.set_course_route_active(conn, selected_id, False)
                st.warning("과목이 비활성화되었습니다. 기존 세션/스냅샷은 유지됩니다.")
                st.rerun()
        else:
            if c2.button("활성화", key="v051_route_on"):
                repository.set_course_route_active(conn, selected_id, True)
                st.success("과목이 활성화되었습니다.")
                st.rerun()


def _render_course_task_routes(conn) -> None:
    st.markdown("### 과목별 Phase B PBL 과제 연결")
    courses = repository.list_course_routes(conn, active_only=False)
    tasks = _get_all_pbl_tasks(conn)
    if not courses:
        st.info("먼저 과목을 등록하세요.")
        return
    if not tasks:
        st.info("먼저 문항 관리 화면에서 Phase B PBL 과제를 등록하세요.")
        return

    course_options = {f"{c['course_id']} - {c['course_name']}": c for c in courses}
    task_options = {f"{t['task_id']} - {t['title']}": t for t in tasks}
    selected_course_label = st.selectbox("과목", list(course_options.keys()), key="v051_task_route_course")
    selected_task_label = st.selectbox("연결할 PBL 과제", list(task_options.keys()), key="v051_task_route_task")
    active = st.checkbox("이 과목에서 이 과제 사용", value=True, key="v051_task_route_active")

    if st.button("과제 연결 저장", type="primary"):
        course = course_options[selected_course_label]
        task = task_options[selected_task_label]
        repository.set_course_task_route(conn, course["course_id"], task["task_id"], active=active)
        st.success("과목별 PBL 과제 연결이 저장되었습니다.")
        st.rerun()

    routes = repository.list_course_task_routes(conn)
    if routes:
        st.markdown("### 연결 목록")
        st.dataframe(pd.DataFrame(routes), use_container_width=True, hide_index=True)


def _get_all_pbl_tasks(conn) -> list[dict]:
    try:
        import db
        return db.get_all_pbl_tasks(conn)
    except Exception:
        return []
