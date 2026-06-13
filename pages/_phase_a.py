from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

import streamlit as st
import db
import phase_a_engine as PA


def _load_pool(conn) -> list[dict]:
    try:
        active = db.get_active_items(conn)
        if active:
            return active
    except Exception:
        pass

    pool_path = os.path.join(os.path.dirname(__file__), "..", "config", "question_pool.json")
    with open(pool_path, encoding="utf-8") as f:
        pool = json.load(f)
    return [i for i in pool["items"] if i.get("active")]


def _sample_questions(items: list[dict]) -> list[dict]:
    qli = [i for i in items if i["axis"] == "qli"]
    mti = [i for i in items if i["axis"] == "mti"]
    picked_q = random.sample(qli, min(5, len(qli)))
    picked_m = random.sample(mti, min(5, len(mti)))
    combined = picked_q + picked_m
    random.shuffle(combined)
    return combined


def render(conn, user_id: str, course_id: str):
    st.title("Phase A — 사전 진단")

    existing = db.load_latest_phase_a(conn, user_id, course_id)
    if existing:
        st.success("✅ 이번 학기 진단을 이미 완료했습니다. Phase B 세션으로 이동하세요.")
        return

    items = _load_pool(conn)
    if len(items) < 10:
        st.error("문항 풀이 부족합니다. 관리자에게 문의하세요.")
        return

    if "phase_a_questions" not in st.session_state:
        st.session_state["phase_a_questions"] = _sample_questions(items)

    questions = st.session_state["phase_a_questions"]

    st.markdown("아래 문항을 읽고 자신에게 해당하는 정도를 선택하세요.")
    st.caption("1=전혀 그렇지 않다  2=그렇지 않다  3=그렇다  4=매우 그렇다")

    responses = {}
    scale = {
        1: "① 전혀 그렇지 않다",
        2: "② 그렇지 않다",
        3: "③ 그렇다",
        4: "④ 매우 그렇다",
    }

    with st.form("phase_a_form"):
        for i, q in enumerate(questions, 1):
            st.write(f"**{i}.** {q['text']}")
            val = st.radio(
                f"문항 {i} 응답",
                list(scale.values()),
                key=q["item_id"],
                horizontal=True,
                label_visibility="collapsed",
            )
            responses[q["item_id"]] = {"item": q, "raw_label": val}
        submitted = st.form_submit_button("제출")

    if submitted:
        resp_list = []
        for item_id, v in responses.items():
            q = v["item"]
            raw_score = list(scale.keys())[list(scale.values()).index(v["raw_label"])]
            resp_list.append({
                "item_id": item_id,
                "axis": q["axis"],
                "score": raw_score,
                "reverse": bool(q.get("reverse", False)),
            })
        try:
            pool_version = db.get_pool_version(conn)
            ep = PA.phase_a_score(resp_list, question_pool_version=pool_version)
            profile_id = db.save_phase_a(conn, user_id, course_id, ep)
            try:
                db.save_phase_a_question_snapshot(conn, profile_id, user_id, course_id, questions, pool_version)
            except Exception:
                pass
            del st.session_state["phase_a_questions"]
            st.success("✅ 진단 완료! Phase B 세션으로 이동하세요.")
            st.info("진단 결과는 학기말 종합 리포트에서 확인할 수 있습니다.")
        except Exception as e:
            st.error(f"처리 중 오류가 발생했습니다: {e}")
