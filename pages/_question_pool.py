
"""pages/_question_pool.py — v0.5 교수용 문항 관리 화면.

Phase A 객관식 문항 풀과 Phase B PBL 과제 풀을 코드 수정 없이 관리한다.
삭제 대신 비활성화를 사용해 과거 측정 해석 가능성을 보존한다.
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "storage"))

import db


def render(conn, prof_id: str, course_id: str) -> None:
    st.title("문항 관리")
    st.caption("교수 관리자 전용 — Phase A 객관식 문항 풀 및 Phase B PBL 과제 관리")
    st.info("삭제 대신 비활성화를 사용합니다. 이미 제출된 세션의 문항/과제 스냅샷은 유지됩니다.")

    tab_a, tab_b = st.tabs(["Phase A 객관식 문항", "Phase B PBL 과제"])
    with tab_a:
        _render_phase_a(conn, prof_id)
    with tab_b:
        _render_phase_b(conn, prof_id)


def _render_phase_a(conn, prof_id: str) -> None:
    st.subheader("Phase A — 객관식 문항 풀")

    constraints = db.check_pool_constraints(conn)
    c1, c2, c3 = st.columns(3)
    c1.metric("문항 풀 버전", db.get_pool_version(conn))
    c2.metric("QLI 활성 문항", constraints["qli_active"])
    c3.metric("MTI 활성 문항", constraints["mti_active"])

    if constraints["phase_a_ready"]:
        st.success("Phase A 진단 가능 상태입니다. QLI/MTI 활성 문항이 각각 5개 이상입니다.")
    for warning in constraints["warnings"]:
        st.warning(warning)

    items = db.get_all_question_items(conn)
    st.markdown("### 문항 목록")
    if items:
        df = pd.DataFrame(items)
        show = df[["item_id", "axis", "text", "reverse", "sub_domain", "difficulty", "active", "pool_version"]].copy()
        show.columns = ["ID", "축", "문항", "역문항", "하위영역", "난이도", "활성", "버전"]
        show["역문항"] = show["역문항"].map({1: "예", 0: "아니오"})
        show["활성"] = show["활성"].map({1: "활성", 0: "대기/비활성"})
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("등록된 문항이 없습니다.")

    st.markdown("### 문항 추가")
    with st.form("v05_add_phase_a_item"):
        axis = st.radio("축", ["qli", "mti"], horizontal=True)
        text = st.text_area("문항 텍스트", height=90)
        col1, col2, col3 = st.columns(3)
        reverse = col1.checkbox("역문항")
        difficulty = col2.selectbox("난이도", ["low", "mid", "high"], index=1)
        sub_domain = col3.text_input("하위 영역", placeholder="예: lp, bf, monitoring")
        custom_id = st.text_input("문항 ID", placeholder="비워두면 자동 생성")
        submitted = st.form_submit_button("문항 등록", type="primary")
        if submitted:
            if not text.strip():
                st.error("문항 텍스트를 입력하세요.")
            else:
                new_id = db.add_question_item(conn, {
                    "item_id": custom_id.strip() or None,
                    "axis": axis,
                    "text": text.strip(),
                    "reverse": reverse,
                    "difficulty": difficulty,
                    "sub_domain": sub_domain.strip() or None,
                }, created_by=prof_id)
                st.success(f"문항이 등록되었습니다. ID: {new_id}. 기본 상태는 대기/비활성입니다.")
                st.rerun()

    if items:
        st.markdown("### 문항 수정 / 활성화 / 비활성화")
        item_ids = [i["item_id"] for i in items]
        selected_id = st.selectbox("대상 문항", item_ids, key="v05_phase_a_selected")
        selected = next(i for i in items if i["item_id"] == selected_id)

        with st.expander("선택 문항 상세", expanded=True):
            st.write(f"**축:** {selected['axis']} · **상태:** {'활성' if selected['active'] else '비활성'}")
            st.write(selected["text"])

            col_a, col_b = st.columns(2)
            if not selected["active"]:
                if col_a.button("활성화", key="v05_activate_item"):
                    ok, msg = db.activate_question_item(conn, selected_id)
                    if ok:
                        st.success(f"활성화되었습니다. 새 풀 버전: {msg}")
                        st.rerun()
                    else:
                        st.error(msg)
            else:
                if col_b.button("비활성화", key="v05_deactivate_item"):
                    db.deactivate_question_item(conn, selected_id)
                    st.warning("비활성화되었습니다. 과거 응답 스냅샷은 유지됩니다.")
                    st.rerun()

            st.caption("수정은 원본을 비활성화하고 수정본을 새 문항으로 등록하는 방식입니다.")
            with st.form("v05_edit_phase_a_item"):
                new_text = st.text_area("수정본 문항", value=selected["text"], height=90)
                new_reverse = st.checkbox("수정본 역문항", value=bool(selected["reverse"]))
                new_difficulty = st.selectbox(
                    "수정본 난이도", ["low", "mid", "high"],
                    index=["low", "mid", "high"].index(selected.get("difficulty") or "mid"),
                )
                save_edit = st.form_submit_button("수정본 저장")
                if save_edit:
                    if not new_text.strip():
                        st.error("수정본 문항을 입력하세요.")
                    else:
                        db.deactivate_question_item(conn, selected_id)
                        new_id = db.add_question_item(conn, {
                            "axis": selected["axis"],
                            "text": new_text.strip(),
                            "reverse": new_reverse,
                            "difficulty": new_difficulty,
                            "sub_domain": selected.get("sub_domain"),
                        }, created_by=prof_id)
                        st.success(f"원본 {selected_id}는 비활성화했고, 수정본 {new_id}를 대기 상태로 등록했습니다.")
                        st.rerun()


def _render_phase_b(conn, prof_id: str) -> None:
    st.subheader("Phase B — PBL 과제 풀")

    tasks = db.get_all_pbl_tasks(conn)
    st.markdown("### 과제 목록")
    if tasks:
        df = pd.DataFrame([{
            "ID": t["task_id"],
            "제목": t["title"],
            "전공": t.get("department") or "공통",
            "난이도": t.get("difficulty") or "mid",
            "목표지표": ", ".join(t.get("target_metrics") or []),
            "기본문항": len(t.get("questions") or []),
            "심화문항": len(t.get("advanced_questions") or []),
            "버전": t.get("task_version"),
            "상태": "활성" if t.get("active") else "비활성",
        } for t in tasks])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("등록된 PBL 과제가 없습니다.")

    st.markdown("### 과제 추가")
    with st.form("v05_add_pbl_task"):
        title = st.text_input("과제 제목")
        department = st.text_input("전공", placeholder="빈칸이면 공통")
        difficulty = st.selectbox("난이도", ["low", "mid", "high"], index=1)
        target_metrics = st.multiselect("목표 지표", ["QLI", "MTI", "Rec", "Recon", "Orc"], default=["QLI", "MTI"])
        trigger_design = st.multiselect(
            "트리거 설계",
            ["인지 충돌", "전제 도전", "다중 해석", "유사 구조 비교", "지식 통합", "역할 분담"],
        )
        questions = []
        for i in range(5):
            val = st.text_area(f"기본 문항 {i+1}", key=f"v05_new_q_{i}", height=70)
            if val.strip():
                questions.append(val.strip())
        advanced = []
        for i in range(2):
            val = st.text_area(f"심화 문항 {i+1}", key=f"v05_new_adv_{i}", height=70)
            if val.strip():
                advanced.append(val.strip())
        add_task = st.form_submit_button("과제 등록", type="primary")
        if add_task:
            if not title.strip() or not questions:
                st.error("과제 제목과 기본 문항 1개 이상을 입력하세요.")
            else:
                task_id = db.add_pbl_task(conn, {
                    "title": title.strip(),
                    "department": department.strip() or None,
                    "difficulty": difficulty,
                    "target_metrics": target_metrics,
                    "trigger_design": trigger_design,
                    "questions": questions,
                    "advanced_questions": advanced,
                }, created_by=prof_id)
                st.success(f"과제가 등록되었습니다. ID: {task_id}")
                st.rerun()

    if tasks:
        st.markdown("### 과제 수정 / 활성화 / 비활성화")
        task_ids = [t["task_id"] for t in tasks]
        selected_id = st.selectbox("대상 과제", task_ids, key="v05_task_selected")
        selected = next(t for t in tasks if t["task_id"] == selected_id)
        with st.expander("선택 과제 상세", expanded=True):
            st.write(f"**제목:** {selected['title']}")
            st.write(f"**전공:** {selected.get('department') or '공통'} · **상태:** {'활성' if selected.get('active') else '비활성'}")
            for i, q in enumerate(selected.get("questions") or [], 1):
                st.write(f"**기본 {i}.** {q}")
            for i, q in enumerate(selected.get("advanced_questions") or [], 1):
                st.write(f"**심화 {i}.** {q}")

            c1, c2 = st.columns(2)
            if selected.get("active"):
                if c1.button("과제 비활성화", key="v05_task_off"):
                    db.toggle_pbl_task_active(conn, selected_id, False)
                    st.warning("과제가 비활성화되었습니다. 과거 세션 스냅샷은 유지됩니다.")
                    st.rerun()
            else:
                if c2.button("과제 활성화", key="v05_task_on"):
                    db.toggle_pbl_task_active(conn, selected_id, True)
                    st.success("과제가 활성화되었습니다.")
                    st.rerun()

            with st.form("v05_edit_pbl_task"):
                new_title = st.text_input("수정 제목", value=selected["title"])
                new_department = st.text_input("수정 전공", value=selected.get("department") or "")
                new_difficulty = st.selectbox(
                    "수정 난이도", ["low", "mid", "high"],
                    index=["low", "mid", "high"].index(selected.get("difficulty") or "mid"),
                )
                new_metrics = st.multiselect(
                    "수정 목표 지표", ["QLI", "MTI", "Rec", "Recon", "Orc"],
                    default=[m for m in (selected.get("target_metrics") or []) if m in ["QLI", "MTI", "Rec", "Recon", "Orc"]],
                )
                new_triggers = st.multiselect(
                    "수정 트리거", ["인지 충돌", "전제 도전", "다중 해석", "유사 구조 비교", "지식 통합", "역할 분담"],
                    default=[t for t in (selected.get("trigger_design") or []) if t in ["인지 충돌", "전제 도전", "다중 해석", "유사 구조 비교", "지식 통합", "역할 분담"]],
                )
                new_qs = []
                for i in range(5):
                    prev = selected.get("questions", [])[i] if i < len(selected.get("questions", [])) else ""
                    val = st.text_area(f"수정 기본 문항 {i+1}", value=prev, key=f"v05_edit_q_{i}", height=70)
                    if val.strip():
                        new_qs.append(val.strip())
                new_adv = []
                for i in range(2):
                    prev = selected.get("advanced_questions", [])[i] if i < len(selected.get("advanced_questions", [])) else ""
                    val = st.text_area(f"수정 심화 문항 {i+1}", value=prev, key=f"v05_edit_adv_{i}", height=70)
                    if val.strip():
                        new_adv.append(val.strip())
                save = st.form_submit_button("과제 수정 저장")
                if save:
                    if not new_title.strip() or not new_qs:
                        st.error("제목과 기본 문항 1개 이상이 필요합니다.")
                    else:
                        db.update_pbl_task(conn, selected_id, {
                            "title": new_title.strip(),
                            "department": new_department.strip() or None,
                            "difficulty": new_difficulty,
                            "target_metrics": new_metrics,
                            "trigger_design": new_triggers,
                            "questions": new_qs,
                            "advanced_questions": new_adv,
                        })
                        st.success("과제가 수정되었습니다. 이미 제출된 세션의 스냅샷은 바뀌지 않습니다.")
                        st.rerun()
