"""
pages/_phase_b.py — Phase B PBL 세션 (07 §3, 09 §3)

PBL 과제 기반 학습자-AI 대화 세션.
세션 종료 → session_compressed에 raw log 저장 → measure_queue 추가
           → 학생에게 "측정 진행 중" 알림 (비동기, 실시간 점수 미공개)

튜터 AI: 직접 답변 제공 금지. 생각을 유도하는 질문 위주.
"""
from __future__ import annotations
import json, os, sys, uuid
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

import streamlit as st
import db

# Phase A 없이 Phase B 접근 방지
# 튜터 AI 시스템 프롬프트 (CRP 측정 AI와 별개 — 학습 대화용)
_TUTOR_SYSTEM = """당신은 학습자의 사고를 돕는 AI 튜터입니다. 직접적인 답을 제공하지 않고, 
학습자가 스스로 탐구하도록 생각을 유도하는 질문을 합니다. 
학습자의 가정과 전제를 부드럽게 도전하고, 다양한 관점을 고려하도록 격려하세요."""

def _select_task(conn, dept: str = "history") -> dict | None:
    """DB의 활성 PBL 과제 중 하나를 선택한다. 전공 과제와 공통 과제를 모두 후보로 본다."""
    tasks = db.get_active_pbl_tasks(conn, dept)
    if not tasks:
        tasks = db.get_active_pbl_tasks(conn)
    return tasks[0] if tasks else None


def _get_client():
    """Anthropic 클라이언트. API 키 없으면 None."""
    try:
        from engines.phase_b_engine.llm_client import AnthropicClient
        key = st.secrets.get("ANTHROPIC_API_KEY", "")
        return AnthropicClient(key) if key else None
    except Exception:
        return None


def _ai_respond(messages: list[dict], task_context: str) -> str:
    """튜터 AI 응답. 클라이언트 없으면 플레이스홀더."""
    client = _get_client()
    if client is None:
        return "(API 키가 설정되지 않아 AI 응답을 생성할 수 없습니다. .streamlit/secrets.toml에 ANTHROPIC_API_KEY를 설정하세요.)"
    try:
        import anthropic
        from engines.phase_b_engine import prompts as P
        aclient = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
        system = _TUTOR_SYSTEM + f"\n\n현재 과제:\n{task_context}"
        api_msgs = [{"role": m["role"], "content": m["content"]}
                    for m in messages if m["role"] in ("user", "assistant")]
        resp = aclient.messages.create(
            model=P.CALL_POLICY["model"], max_tokens=800,
            system=system, messages=api_msgs, temperature=0.7)
        return resp.content[0].text
    except Exception as e:
        return f"(AI 응답 오류: {e})"


def _end_session(conn, user_id, course_id, session_id,
                 messages, task_id, session_start, dept, grade):
    """세션 종료 처리: raw log 저장 → 큐 추가 → status 업데이트."""
    session_end = datetime.now(timezone.utc).isoformat()
    raw_log = {
        "session_id": session_id,
        "student_id": user_id,
        "course_id": course_id,
        "task_id": task_id,
        "session_start": session_start,
        "session_end": session_end,
        "department": dept,
        "student_grade": grade,
        "session_number": _count_sessions(conn, user_id, course_id) + 1,
        "messages": [
            {"turn_id": i+1, "speaker": "student" if m["role"]=="user" else "ai",
             "text": m["content"], "timestamp": session_start}
            for i, m in enumerate(messages)
        ],
    }
    import hashlib
    raw_hash = "sha256:" + hashlib.sha256(
        json.dumps(raw_log, ensure_ascii=False).encode()).hexdigest()
    # session_compressed에 raw log 저장 (B1이 처리할 원본)
    conn.execute("""
        INSERT OR REPLACE INTO session_compressed(session_id, compressed_json, raw_log_hash)
        VALUES(?,?,?)
    """, (session_id, json.dumps(raw_log, ensure_ascii=False), raw_hash))
    conn.commit()
    db.update_session_status(conn, session_id, "pending_measure", session_end=session_end)
    db.push_measure_queue(conn, session_id)


def _count_sessions(conn, student_id, course_id) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE student_id=? AND course_id=? AND phase='B'",
        (student_id, course_id)).fetchone()
    return row[0] if row else 0


def render(conn, user_id: str, course_id: str):
    st.title("Phase B — PBL 세션")

    # Phase A 완료 체크
    ep = db.load_latest_phase_a(conn, user_id, course_id)
    if not ep:
        st.warning("⚠️ Phase A 진단을 먼저 완료하세요.")
        return

    if "current_task_snapshot" in st.session_state:
        task = st.session_state["current_task_snapshot"]
    else:
        task = _select_task(conn, dept="history")
    if not task:
        st.error("활성화된 PBL 과제가 없습니다. 교수 관리자 화면에서 Phase B 과제를 등록·활성화하세요.")
        return
    n_q = len(task["questions"])

    # 세션 초기화
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
        st.session_state["session_start"] = datetime.now(timezone.utc).isoformat()
        st.session_state["chat_messages"] = []
        st.session_state["current_q"] = 0
        st.session_state["session_ended"] = False
        db.save_session(conn, {
            "session_id": st.session_state["session_id"],
            "student_id": user_id, "course_id": course_id,
            "task_id": task["task_id"], "phase": "B",
            "status": "active",
            "session_start": st.session_state["session_start"],
        })
        st.session_state["current_task_snapshot"] = task
        db.save_session_task_snapshot(conn, st.session_state["session_id"], user_id, course_id, task)

    if st.session_state.get("session_ended"):
        st.success("✅ 세션이 종료되었습니다. 측정이 진행 중입니다. 결과는 다음 접속 시 확인됩니다.")
        if st.button("새 세션 시작"):
            for k in ["session_id", "session_start", "chat_messages",
                      "current_q", "session_ended", "current_task_snapshot"]:
                st.session_state.pop(k, None)
            st.rerun()
        return

    q_idx = st.session_state["current_q"]
    with st.expander(f"📋 과제 [{q_idx+1}/{n_q}]", expanded=True):
        st.write(task["questions"][q_idx])

    # 채팅 표시
    for msg in st.session_state["chat_messages"]:
        with st.chat_message("user" if msg["role"]=="user" else "assistant"):
            st.write(msg["content"])

    col1, col2 = st.columns([5, 1])
    with col1:
        user_input = st.chat_input("AI에게 질문하거나 생각을 입력하세요")
    with col2:
        if q_idx < n_q - 1 and st.button("다음 문항 →"):
            st.session_state["current_q"] += 1
            st.rerun()

    if user_input:
        st.session_state["chat_messages"].append(
            {"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)
        with st.chat_message("assistant"):
            with st.spinner(""):
                reply = _ai_respond(
                    st.session_state["chat_messages"],
                    task["questions"][q_idx])
            st.write(reply)
        st.session_state["chat_messages"].append(
            {"role": "assistant", "content": reply})
        st.rerun()

    st.divider()
    if st.button("🔚 세션 종료 및 제출", type="primary"):
        if len(st.session_state["chat_messages"]) < 2:
            st.warning("AI와 최소 한 번 이상 대화 후 세션을 종료하세요.")
        else:
            _end_session(
                conn, user_id, course_id,
                st.session_state["session_id"],
                st.session_state["chat_messages"],
                task["task_id"],
                st.session_state["session_start"],
                dept="history", grade=2)
            st.session_state["session_ended"] = True
            st.rerun()
