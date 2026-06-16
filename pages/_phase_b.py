"""
pages/_phase_b.py — Phase B PBL 세션 (07 §3, 09 §3)

PBL 과제 기반 학습자-AI 대화 세션.
세션 종료 → session_compressed에 raw log 저장 → measure_queue 추가
           → 학생에게 "측정 진행 중" 알림 (비동기, 실시간 점수 미공개)

튜터 AI: 직접 답변 제공 금지. 생각을 유도하는 질문 위주.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))

import db
from features.course_routing import repository as course_routing_repo

# Phase A 없이 Phase B 접근 방지
# 튜터 AI 시스템 프롬프트 (CRP 측정 AI와 별개 — 학습 대화용)
_TUTOR_SYSTEM = """당신은 학습자의 사고를 돕는 AI 튜터입니다.

역할:
- 정답을 직접 제공하지 말고, 학습자가 자신의 판단 기준과 전제를 스스로 점검하도록 돕습니다.
- 학습자의 답변을 짧게 받아준 뒤, 가장 중요한 판단 기준 하나를 짚어 줍니다.
- 대화는 넓게 흩뜨리지 말고 한 지점을 깊게 파고듭니다.

응답 규칙:
1. 후속 질문은 기본 1개만 제시합니다.
2. 꼭 필요한 경우에도 후속 질문은 최대 2개까지만 허용합니다.
3. 3개 이상의 질문, 번호형 질문 목록, 서로 다른 방향의 질문 다발은 금지합니다.
4. 질문이 2개일 때는 두 질문이 같은 논점을 더 깊게 보기 위한 밀접한 질문이어야 합니다.
5. 응답은 3~5문장 안에서 간결하게 작성합니다.
6. 학생이 바로 무엇에 답해야 하는지 명확해야 합니다.
"""


def _select_task(conn, course_id: str) -> dict | None:
    """선택 과목에 연결된 Phase B 과제를 우선 선택한다.

    v0.5.1 원칙:
    - Phase A 객관식 문항은 공통 유지
    - Phase B PBL 과제만 course_id별로 라우팅
    - 아직 연결된 과제가 없으면 기존 활성 과제 풀로 fallback해 파일럿 진입을 막지 않는다.
    """
    tasks = course_routing_repo.get_active_pbl_tasks_for_course(conn, course_id)
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


def _limit_followup_questions(text: str, max_questions: int = 2) -> str:
    """시연 UX 안전장치: 응답 내 물음표 기준 후속 질문 수를 제한한다."""
    cleaned = (text or "").strip()
    question_marks = [idx for idx, ch in enumerate(cleaned) if ch in {"?", "？"}]
    if len(question_marks) <= max_questions:
        return cleaned
    return cleaned[: question_marks[max_questions - 1] + 1].strip()


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
        api_msgs = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m["role"] in ("user", "assistant")
        ]
        resp = aclient.messages.create(
            model=P.CALL_POLICY["model"],
            max_tokens=500,
            system=system,
            messages=api_msgs,
            temperature=0.4,
        )
        return _limit_followup_questions(resp.content[0].text)
    except Exception as e:
        return f"(AI 응답 오류: {e})"


def _end_session(conn, user_id, course_id, session_id, messages, task_id, session_start, dept, grade):
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
            {
                "turn_id": i + 1,
                "question_index": m.get("q_idx"),
                "speaker": "student" if m["role"] == "user" else "ai",
                "text": m["content"],
                "timestamp": session_start,
            }
            for i, m in enumerate(messages)
        ],
    }
    import hashlib

    raw_hash = "sha256:" + hashlib.sha256(json.dumps(raw_log, ensure_ascii=False).encode()).hexdigest()
    # session_compressed에 raw log 저장 (B1이 처리할 원본)
    conn.execute(
        """
        INSERT OR REPLACE INTO session_compressed(session_id, compressed_json, raw_log_hash)
        VALUES(?,?,?)
    """,
        (session_id, json.dumps(raw_log, ensure_ascii=False), raw_hash),
    )
    conn.commit()
    db.update_session_status(conn, session_id, "pending_measure", session_end=session_end)
    db.push_measure_queue(conn, session_id)


def _count_sessions(conn, student_id, course_id) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM sessions WHERE student_id=? AND course_id=? AND phase='B'",
        (student_id, course_id),
    ).fetchone()
    return row[0] if row else 0


def _messages_for_question(messages: list[dict], q_idx: int) -> list[dict]:
    """현재 문항 메시지만 표시한다. 구버전 메시지는 0번 문항으로 간주한다."""
    return [m for m in messages if int(m.get("q_idx", 0)) == q_idx]


def _has_exchange(messages: list[dict], q_idx: int) -> bool:
    q_messages = _messages_for_question(messages, q_idx)
    has_user = any(m["role"] == "user" for m in q_messages)
    has_assistant = any(m["role"] == "assistant" for m in q_messages)
    return has_user and has_assistant


def _render_question_header(question: str, q_idx: int, n_q: int) -> None:
    st.markdown(f"### 현재 문항: {q_idx + 1} / {n_q}")
    st.info(question)
    st.caption("이 문항에서는 정답보다 판단 기준, 전제, 책임의 근거를 스스로 구성하는 과정이 중요합니다.")


def _render_messages(messages: list[dict]) -> None:
    for msg in messages:
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.write(msg["content"])


def _render_previous_questions(task: dict, messages: list[dict], current_q: int) -> None:
    if current_q <= 0:
        return

    with st.expander("이전 문항 대화 보기", expanded=False):
        for prev_idx in range(current_q):
            prev_messages = _messages_for_question(messages, prev_idx)
            if not prev_messages:
                continue
            st.markdown(f"#### 과제 {prev_idx + 1}/{len(task['questions'])}")
            st.caption(task["questions"][prev_idx])
            _render_messages(prev_messages)
            st.divider()


def _render_answer_form(session_id: str, q_idx: int, current_messages: list[dict]) -> tuple[bool, str]:
    """현재 위치에 답변 입력창을 렌더링한다.

    st.chat_input은 화면 최하단에 고정되므로, 시연 UX에서는 text_area 기반 입력창을 사용한다.
    답변창은 현재 문항 대화 바로 아래, 다음 문항 이동 버튼 바로 위에 위치한다.
    """
    st.markdown("#### 답변 입력")
    form_key = f"phase_b_answer_form_{session_id}_{q_idx}_{len(current_messages)}"
    with st.form(form_key, clear_on_submit=True):
        user_input = st.text_area(
            "AI에게 질문하거나 생각을 입력하세요",
            placeholder="AI에게 질문하거나 생각을 입력하세요",
            height=120,
            label_visibility="collapsed",
        )
        submitted = st.form_submit_button("AI에게 답변 보내기", type="primary")
    return submitted, user_input.strip()


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
        task = _select_task(conn, course_id)
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
        db.save_session(
            conn,
            {
                "session_id": st.session_state["session_id"],
                "student_id": user_id,
                "course_id": course_id,
                "task_id": task["task_id"],
                "phase": "B",
                "status": "active",
                "session_start": st.session_state["session_start"],
            },
        )
        st.session_state["current_task_snapshot"] = task
        db.save_session_task_snapshot(conn, st.session_state["session_id"], user_id, course_id, task)

    if st.session_state.get("session_ended"):
        st.success("✅ 세션이 종료되었습니다. 측정이 진행 중입니다. 결과는 다음 접속 시 확인됩니다.")
        if st.button("새 세션 시작"):
            for k in [
                "session_id",
                "session_start",
                "chat_messages",
                "current_q",
                "session_ended",
                "current_task_snapshot",
            ]:
                st.session_state.pop(k, None)
            st.rerun()
        return

    q_idx = st.session_state["current_q"]
    messages = st.session_state["chat_messages"]
    current_messages = _messages_for_question(messages, q_idx)

    _render_question_header(task["questions"][q_idx], q_idx, n_q)
    st.divider()

    _render_messages(current_messages)

    submitted, user_input = _render_answer_form(st.session_state["session_id"], q_idx, current_messages)
    if submitted:
        if not user_input:
            st.warning("답변을 입력한 뒤 전송하세요.")
            return
        st.session_state["chat_messages"].append({"role": "user", "content": user_input, "q_idx": q_idx})
        with st.spinner("AI가 응답을 생성하는 중입니다..."):
            reply = _ai_respond(
                _messages_for_question(st.session_state["chat_messages"], q_idx),
                task["questions"][q_idx],
            )
        st.session_state["chat_messages"].append({"role": "assistant", "content": reply, "q_idx": q_idx})
        st.rerun()

    can_advance = q_idx < n_q - 1 and _has_exchange(messages, q_idx)
    can_submit = q_idx == n_q - 1 and _has_exchange(messages, q_idx)

    if q_idx < n_q - 1:
        if st.button("다음 문항으로 이동 →", disabled=not can_advance, type="secondary"):
            st.session_state["current_q"] += 1
            st.rerun()
        if not can_advance:
            st.caption("현재 문항에서 학생 답변 1회와 AI 응답 1회가 있어야 다음 문항으로 이동할 수 있습니다.")
    else:
        st.success("마지막 문항입니다. 답변을 완료한 뒤 세션을 제출하세요.")
        if st.button("🔚 세션 종료 및 제출", type="primary", disabled=not can_submit):
            _end_session(
                conn,
                user_id,
                course_id,
                st.session_state["session_id"],
                st.session_state["chat_messages"],
                task["task_id"],
                st.session_state["session_start"],
                dept=course_id,
                grade=2,
            )
            st.session_state["session_ended"] = True
            st.rerun()
        if not can_submit:
            st.caption("마지막 문항에서 학생 답변 1회와 AI 응답 1회가 있어야 제출할 수 있습니다.")

    st.divider()
    _render_previous_questions(task, messages, q_idx)

    if q_idx < n_q - 1:
        st.caption("모든 문항을 순서대로 진행한 뒤 마지막 문항에서 세션을 제출할 수 있습니다.")
