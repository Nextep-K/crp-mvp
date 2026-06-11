"""
pages/_student_flow.py — 학생용 연속 플로우

학생에게는 하나의 활동처럼 보이게 한다.
내부적으로는 Phase A(자기보고)와 Phase B(행동 측정)를 분리 저장한다.

흐름:
  1. 학습 성향 체크(Phase A)
  2. AI와 함께 문제 탐색(Phase B)
  3. 제출 완료 / 측정 진행 중
  4. 결과 리포트는 별도 버튼에서 확인
"""
from __future__ import annotations

import json
import os
import random
import sys

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

import db
import phase_a_engine as PA


def _load_pool(conn) -> list[dict]:
    """DB의 활성 Phase A 문항을 읽는다. v0.5부터 JSON 직접 로딩을 하지 않는다."""
    return db.get_active_items(conn)


def _sample_questions(items: list[dict]) -> list[dict]:
    qli = [i for i in items if i["axis"] == "qli"]
    mti = [i for i in items if i["axis"] == "mti"]
    picked_q = random.sample(qli, min(5, len(qli)))
    picked_m = random.sample(mti, min(5, len(mti)))
    combined = picked_q + picked_m
    random.shuffle(combined)
    return combined

def _progress(step: int) -> None:
    labels = ["① 사전 체크", "② AI 문제 탐색", "③ 제출 완료"]
    cols = st.columns(3)
    for idx, col in enumerate(cols, 1):
        with col:
            if idx < step:
                st.success(labels[idx - 1])
            elif idx == step:
                st.info(labels[idx - 1])
            else:
                st.caption(labels[idx - 1])


def _render_phase_a(conn, user_id: str, course_id: str) -> None:
    _progress(1)
    st.title("오늘의 CRP 활동")
    st.subheader("1단계 — 학습 성향 체크")
    st.caption("이 단계는 자기 인식 기준선을 확인하기 위한 사전 체크입니다. 결과는 즉시 공개되지 않습니다.")

    items = _load_pool(conn)
    if len(items) < 10:
        st.error("문항 풀이 부족합니다. 관리자에게 문의하세요.")
        return

    if "phase_a_questions" not in st.session_state:
        st.session_state["phase_a_questions"] = _sample_questions(items)

    questions = st.session_state["phase_a_questions"]
    scale = {
        1: "① 전혀 그렇지 않다",
        2: "② 그렇지 않다",
        3: "③ 그렇다",
        4: "④ 매우 그렇다",
    }
    responses: dict[str, dict] = {}

    with st.form("student_flow_phase_a_form"):
        for i, q in enumerate(questions, 1):
            st.write(f"**{i}.** {q['text']}")
            val = st.radio(
                f"문항 {i} 응답",
                list(scale.values()),
                key=f"flow_{q['item_id']}",
                horizontal=True,
                label_visibility="collapsed",
            )
            responses[q["item_id"]] = {"item": q, "raw_label": val}
        submitted = st.form_submit_button("사전 체크 완료 후 문제 탐색으로 이동", type="primary")

    if submitted:
        resp_list = []
        for item_id, v in responses.items():
            q = v["item"]
            raw_score = list(scale.keys())[list(scale.values()).index(v["raw_label"])]
            resp_list.append(
                {
                    "item_id": item_id,
                    "axis": q["axis"],
                    "score": raw_score,
                    "reverse": q.get("reverse", False),
                }
            )
        try:
            pool_version = db.get_pool_version(conn)
            ep = PA.phase_a_score(resp_list, question_pool_version=pool_version)
            profile_id = db.save_phase_a(conn, user_id, course_id, ep)
            db.save_phase_a_question_snapshot(conn, profile_id, user_id, course_id, questions, pool_version)
            st.session_state.pop("phase_a_questions", None)
            st.session_state["flow_phase_b_started"] = False
            st.success("사전 체크가 저장되었습니다. 다음 단계로 이동합니다.")
            st.rerun()
        except Exception as exc:
            st.error(f"처리 중 오류가 발생했습니다: {exc}")


def _render_phase_b_intro(user_id: str, course_id: str) -> None:
    _progress(2)
    st.title("오늘의 CRP 활동")
    st.subheader("2단계 — AI와 함께 문제 탐색")
    st.markdown(
        """
        이제 PBL 과제를 수행합니다.  
        이 단계에서는 정답만 찾는 것이 아니라, 질문을 만들고 전제를 점검하며 자신의 판단을 구성하는 과정이 기록됩니다.
        """
    )
    st.warning("Phase A 결과는 여기서 공개되지 않으며, Phase B 점수와 합산되지 않습니다.")
    st.caption(f"학생: {user_id} · 과목: {course_id}")
    if st.button("PBL 세션 시작", type="primary"):
        st.session_state["flow_phase_b_started"] = True
        st.rerun()


def _render_submitted() -> None:
    _progress(3)
    st.title("제출 완료")
    st.success("세션이 종료되었습니다. 측정이 진행 중입니다.")
    st.info("학생은 대기하지 않아도 됩니다. 결과는 측정 완료 후 리포트에서 확인할 수 있습니다.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("결과 리포트 확인", use_container_width=True):
            st.session_state["student_flow_view"] = "report"
            st.rerun()
    with col2:
        if st.button("새 PBL 세션 시작", use_container_width=True):
            for key in [
                "session_id",
                "session_start",
                "chat_messages",
                "current_q",
                "session_ended",
            ]:
                st.session_state.pop(key, None)
            st.session_state["flow_phase_b_started"] = False
            st.rerun()


def _render_activity(conn, user_id: str, course_id: str) -> None:
    ep = db.load_latest_phase_a(conn, user_id, course_id)

    if not ep:
        _render_phase_a(conn, user_id, course_id)
        return

    if st.session_state.get("session_ended"):
        _render_submitted()
        return

    if not st.session_state.get("flow_phase_b_started"):
        _render_phase_b_intro(user_id, course_id)
        return

    from pages import _phase_b

    _progress(2)
    _phase_b.render(conn, user_id, course_id)


def render(conn, user_id: str, course_id: str) -> None:
    view = st.session_state.get("student_flow_view", "activity")
    if view == "report":
        from pages import _report

        _report.render(conn, user_id, course_id)
        return

    _render_activity(conn, user_id, course_id)
