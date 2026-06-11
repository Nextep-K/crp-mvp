"""
workers/measure_worker.py — 비동기 측정 처리 (09 §3)

세션 종료 후 큐에서 job을 꺼내 전체 CRP 파이프라인을 실행한다.
  B1(압축본 생성 + Class 분류) → 모듈 B(LLM 33회) → 모듈 A(연산) → session_metrics 저장

MVP: B1 추적 에이전트를 내장 (별도 에이전트 서버 없음, 09 §3).
     B1 분류기는 규칙 기반 MVP 플레이스홀더 + CLS-S 하이브리드.
     상세 B1 구현은 00 §7 범위 밖 (B1 에이전트 설계 시).
에러 처리: 06 §1 재시도 정책. retry_count >= MAX_RETRY → failed.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines", "phase_b_engine"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "engines"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "storage"))

import compute_module as A
import db
from aux_prompts import classify_class_s
from judgment_module import LLMClient
from phase_b_engine import measure_session
from crp_types import CLASSIFIER_VERSION

POLL_INTERVAL = 10      # 09 §3
MAX_RETRY = 3           # 06 §1

# ════════════════════════════════════════════════════════════════════════
# B1 MVP 규칙 기반 분류기 (00 §7 — 상세 구현은 B1 에이전트 설계 시)
# 위계 우선순위: S > A > B > C (02 §3.2)
# ════════════════════════════════════════════════════════════════════════

_PATTERNS: dict[str, list[str]] = {
    # Class S — 문제 재정의
    "S-1": ["이 질문이 올바른가", "프레임으로 접근", "전제 자체", "가정이 옳", "올바른 질문인가"],
    "S-2": ["다르게 정의하면", "범위를 바꾸", "조건을 변경", "변수도 고려", "문제를 재정의"],
    "S-3": ["진짜 문제는", "이 질문 자체가", "에서 비롯된", "근본적인 문제"],
    # Class A — 자기 부정
    "A-1": ["잘못 이해했", "처음 생각이 틀", "아니다, 다시", "내가 틀렸", "철회"],
    "A-2": ["내가 앞서", "충돌한다", "모순된다", "일치하지 않", "앞의 논거와"],
    "A-3": ["수정이 필요", "바꿔야겠", "다시 생각해야", "재고해야"],
    # Class B — 전략 수정
    "B-1": ["다른 방향으로", "방법을 바꾸", "접근 방식을 바꾸", "새로운 방법"],
    "B-2": ["원하는 게 아니", "대신 이렇게", "이건 아니고", "거부하고"],
    "B-3": ["어떤 기준으로", "왜 그것이 옳", "그 기준은 무엇"],
    # Class C — 성찰
    "C-1": ["이렇게 생각한 이유", "내 추론은", "내가 이렇게 생각하는"],
    "C-2": ["확실하지 않지만", "잘 모르겠지만", "불확실하지만", "확실하지 않다"],
    "C-3": ["처음에는", "지금은 다르게", "생각이 바뀌었"],
}

_CLASS_ORDER = ["S-1", "S-2", "S-3", "A-1", "A-2", "A-3",
                "B-1", "B-2", "B-3", "C-1", "C-2", "C-3"]


def b1_classify(text: str) -> tuple[str, float]:
    """규칙 기반 Class 분류. (label, confidence) 반환. 위계 우선순위 S>A>B>C."""
    for label in _CLASS_ORDER:
        patterns = _PATTERNS[label]
        hits = sum(1 for p in patterns if p in text)
        if hits > 0:
            conf = min(0.5 + hits * 0.2, 0.85)   # 규칙 기반 최대 0.85
            return label, conf
    return "N", 1.0


def _build_metadata(messages: list[dict], session_start: str,
                    session_end: str) -> dict:
    """04 §1.3 메타데이터 계산."""
    student_msgs = [m for m in messages if m.get("speaker") == "student"]
    total_student = len(student_msgs)
    if total_student == 0:
        return {
            "total_turns": len(messages), "student_turn_count": 0,
            "student_question_count": 0, "ai_turn_count": len(messages),
            "avg_utterance_length": 0.0, "question_ratio": 0.0,
            "repeat_ratio": 0.0, "session_duration_min": 0.0,
            "classifier_version": CLASSIFIER_VERSION, "raw_log_hash": "",
        }
    question_marks = sum(1 for m in student_msgs if "?" in m.get("text", ""))
    question_words = sum(1 for m in student_msgs
                         if any(w in m.get("text","")
                                for w in ["가","인가","할까","어떻게","왜","무엇"]))
    q_count = max(question_marks, question_words)
    avg_len = sum(len(m.get("text", "")) for m in student_msgs) / total_student
    repeat_phrases = {"네", "좋아요", "알겠어요", "그렇군요", "맞아요", "ㅇㅇ"}
    repeat_count = sum(1 for m in student_msgs
                       if m.get("text", "").strip() in repeat_phrases)
    from datetime import datetime
    try:
        t0 = datetime.fromisoformat(session_start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(session_end.replace("Z", "+00:00"))
        dur = (t1 - t0).total_seconds() / 60
    except Exception:
        dur = 0.0
    return {
        "total_turns": len(messages),
        "student_turn_count": total_student,
        "student_question_count": q_count,
        "ai_turn_count": len(messages) - total_student,
        "avg_utterance_length": round(avg_len, 1),
        "question_ratio": round(q_count / total_student, 3),
        "repeat_ratio": round(repeat_count / total_student, 3),
        "session_duration_min": round(dur, 1),
        "classifier_version": CLASSIFIER_VERSION,
        "raw_log_hash": "",   # MVP: 원본 해시 미구현 (04 §1.3 선택 필드)
    }


def build_compressed(raw_log: dict, client: Optional[LLMClient] = None,
                     sleep_fn=time.sleep) -> dict:
    """B1 MVP: raw_log(chat messages) → 04 §1 compressed 스키마.
    class_confidence < 0.6 경계 발화만 CLS-S 호출 (비용 최소화, 05 §보조).
    """
    messages = raw_log.get("messages", [])
    compressed_utterances = []
    for i, m in enumerate(messages):
        speaker = m.get("speaker", "ai")
        text = m.get("text", "")
        turn_id = i + 1
        utt: dict = {
            "turn_id": turn_id, "speaker": speaker,
            "text": text, "timestamp": m.get("timestamp", ""),
        }
        if speaker == "student" and text.strip():
            label, conf = b1_classify(text)
            # CLS-S 하이브리드: confidence < 0.6 경계 발화만 LLM 보조
            if conf < 0.6 and client is not None:
                context = messages[max(0, i-2):i]
                cls_result = classify_class_s(client, text, context, label,
                                              sleep_fn=sleep_fn)
                if cls_result.is_class_s and cls_result.sub_label:
                    label = cls_result.sub_label
                    conf = cls_result.confidence
                elif cls_result.fallback_label:
                    label = cls_result.fallback_label
                    conf = max(conf, 0.6)
            utt.update({"class_label": label, "class_confidence": conf,
                        "evidence_flag": conf >= 0.8})
        compressed_utterances.append(utt)

    metadata = _build_metadata(
        messages,
        raw_log.get("session_start", ""),
        raw_log.get("session_end", ""),
    )
    return {
        "schema_version": "1.0_f1",
        "session_id": raw_log.get("session_id", ""),
        "student_id": raw_log.get("student_id", ""),
        "course_id": raw_log.get("course_id", ""),
        "task_id": raw_log.get("task_id"),
        "phase": "B",
        "session_start": raw_log.get("session_start", ""),
        "session_end": raw_log.get("session_end", ""),
        "compressed_utterances": compressed_utterances,
        "metadata": metadata,
        "student_grade": raw_log.get("student_grade", ""),
        "department": raw_log.get("department", ""),
        "session_number": raw_log.get("session_number", 1),
    }


# ════════════════════════════════════════════════════════════════════════
# 단일 job 처리
# ════════════════════════════════════════════════════════════════════════

def process_job(conn, job: dict, client: LLMClient, params: dict,
                sleep_fn=time.sleep) -> bool:
    """한 측정 job 실행. 성공 True, 실패 False."""
    session_id = job["session_id"]
    try:
        # raw log 로드
        row = conn.execute(
            "SELECT compressed_json FROM session_compressed WHERE session_id=?",
            (session_id,)).fetchone()
        if not row:
            raise ValueError(f"session_compressed 없음: {session_id}")
        raw_log = json.loads(row["compressed_json"])

        # 과거 시계열 (Velocity/Grokking용)
        student_id = raw_log.get("student_id", "")
        course_id = raw_log.get("course_id", "")
        metrics_history = db.load_metrics_history(conn, student_id, course_id)

        # avg_session_min 계산 (disengagement 조건④)
        all_sessions = db.load_metrics_history(conn, student_id, course_id,
                                               exclude_disengaged=False)
        avg_session_min = None
        if all_sessions:
            durs = [s.get("session_duration_min", 0) for s in all_sessions
                    if s.get("session_duration_min")]
            avg_session_min = sum(durs) / len(durs) if durs else None

        # B1: 압축본 생성
        compressed = build_compressed(raw_log, client, sleep_fn)

        # measure_session: B + A 파이프라인
        crp_output = measure_session(
            compressed, client, params,
            metrics_history=metrics_history,
            avg_session_min=avg_session_min,
            sleep_fn=sleep_fn,
        )

        # 저장
        db.save_crp_output(conn, crp_output, course_id)
        db.update_session_status(conn, session_id, "measured")
        db.update_queue_status(conn, job["job_id"], "done")
        return True

    except Exception as e:
        print(f"[worker] job {job['job_id']} 실패: {e}")
        return False


# ════════════════════════════════════════════════════════════════════════
# 메인 루프 (09 §3)
# ════════════════════════════════════════════════════════════════════════

def run_worker(db_path: str, client: LLMClient, params: dict,
               poll_interval: int = POLL_INTERVAL,
               max_iterations: Optional[int] = None,
               sleep_fn=time.sleep) -> None:
    """큐 폴링 루프. max_iterations=None이면 무한 루프(운영용)."""
    conn = db.get_connection(db_path)
    iteration = 0
    print("[worker] 시작")
    while True:
        if max_iterations is not None and iteration >= max_iterations:
            break
        iteration += 1
        job = db.pop_measure_queue(conn)
        if job:
            print(f"[worker] job 처리: {job['job_id']}")
            ok = process_job(conn, job, client, params)
            if not ok:
                retry = conn.execute(
                    "SELECT retry_count FROM measure_queue WHERE job_id=?",
                    (job["job_id"],)).fetchone()["retry_count"]
                if retry < MAX_RETRY:
                    db.update_queue_status(conn, job["job_id"], "pending",
                                           increment_retry=True)
                else:
                    db.update_queue_status(conn, job["job_id"], "failed")
                    db.update_session_status(conn, job["session_id"], "failed")
                    print(f"[worker] job {job['job_id']} 최대 재시도 초과 → failed")
        else:
            sleep_fn(poll_interval)
