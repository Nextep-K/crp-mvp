import json
import sqlite3
import uuid

import db
import prompts as P
import compute_module as A
from measure_worker import build_compressed, process_job, MAX_RETRY

NULL = lambda *a: None


class GoodClient:
    def complete(self, system, user, **kw):
        for item, sp in P.SYSTEM_PROMPTS.items():
            if sp == system:
                lo, _ = P.ITEM_SCALE[item]
                score = lo if lo == 0 else 7
                return json.dumps({"score": score, "evidence": f"근거({item})"}, ensure_ascii=False)
        return json.dumps({"is_class_s": False, "fallback_label": "C-1", "confidence": 0.8, "reason": "fallback"}, ensure_ascii=False)


def new_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    db.init_schema(conn)
    db.upsert_student(conn, "u1")
    db.upsert_course(conn, "c1", "한국사", "history")
    return conn


def sample_raw(sid):
    return {
        "session_id": sid, "student_id":"u1", "course_id":"c1", "task_id":"t1",
        "session_start":"2026-04-01T09:00:00Z", "session_end":"2026-04-01T09:45:00Z",
        "department":"history", "student_grade":2, "session_number":1,
        "messages":[
            {"speaker":"student", "text":"이순신의 전략은 왜 효과적이었는가?"},
            {"speaker":"ai", "text":"좋은 질문이에요."},
            {"speaker":"student", "text":"잘못 이해했다, 다시 접근하면"},
            {"speaker":"student", "text":"이 질문이 올바른가?"},
            {"speaker":"student", "text":"전제 자체를 다시 살펴야 한다"},
            {"speaker":"student", "text":"처음에는 단순히 전략 문제라 생각했는데 지금은 다르게 본다"},
        ],
    }


def test_build_compressed_and_process_job():
    sid = str(uuid.uuid4())
    raw = sample_raw(sid)
    compressed = build_compressed(raw, None, NULL)
    assert compressed["schema_version"] == "1.0_f1"
    assert any(u.get("class_label") == "S-1" for u in compressed["compressed_utterances"])
    assert compressed["metadata"]["student_turn_count"] == 5

    conn = new_db()
    db.save_session(conn, {"session_id": sid, "student_id":"u1", "course_id":"c1", "phase":"B", "status":"pending_measure", "session_start":raw["session_start"]})
    conn.execute("INSERT INTO session_compressed(session_id, compressed_json, raw_log_hash) VALUES(?,?,?)", (sid, json.dumps(raw, ensure_ascii=False), "sha256:x"))
    conn.commit()
    db.push_measure_queue(conn, sid)
    job = db.pop_measure_queue(conn)
    params = A.resolve_params({"institution": {"id":"BNU", "defaults": {}}, "departments": [{"id":"history", "tau_baseline_seed": {"MTI":1.2,"QLI":1.0,"Rec":0.8,"Recon":1.1,"Orc":0.9}}]}, "history")
    assert process_job(conn, job, GoodClient(), params, sleep_fn=NULL)
    assert conn.execute("SELECT status FROM measure_queue WHERE job_id=?", (job["job_id"],)).fetchone()[0] == "done"
    metrics = conn.execute("SELECT mti, qli, low_reliability FROM session_metrics WHERE session_id=?", (sid,)).fetchone()
    assert metrics is not None
    assert metrics["mti"] is not None
