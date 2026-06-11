"""
db.py — CRP SQLite 저장 계층 (09 §2, 04 §4)

WAL 모드로 MVP 30명 동시 쓰기 안전(09 §4).
연결을 주입받는 순수 함수로 구성 — 테스트는 :memory: 사용.
UI CRUD(pages/*)는 step 5(UI 단계)에서 추가한다.

데이터 보존 정책 (04 §5) — 시행은 운영 단계. 현재는 주석으로 명시:
  session_compressed  5년   session_metrics  10년
  session_evidence    3년   phase_a_results   5년
  parameter_configs   영구(삭제 금지)
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


# ════════════════════════════════════════════════════════════════════════
# 연결
# ════════════════════════════════════════════════════════════════════════

def get_connection(db_path: str = "storage/data.db") -> sqlite3.Connection:
    """WAL 모드 SQLite 연결. row_factory=Row (dict-like 접근)."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")    # 09 §4 동시 쓰기 안전
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ════════════════════════════════════════════════════════════════════════
# 스키마 (04 §4 ERD 전체)
# ════════════════════════════════════════════════════════════════════════

_DDL = """
CREATE TABLE IF NOT EXISTS students (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS courses (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    dept        TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS enrollments (
    student_id  TEXT NOT NULL REFERENCES students(id),
    course_id   TEXT NOT NULL REFERENCES courses(id),
    enrolled_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (student_id, course_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    student_id      TEXT NOT NULL REFERENCES students(id),
    course_id       TEXT NOT NULL REFERENCES courses(id),
    task_id         TEXT,
    phase           TEXT NOT NULL CHECK(phase IN ('A','B')),
    status          TEXT NOT NULL DEFAULT 'active'
                         CHECK(status IN ('active','pending_measure','measured','failed')),
    session_start   TEXT NOT NULL,
    session_end     TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- 04 §4 session_compressed (1:1, Phase B only, 보존 5년)
CREATE TABLE IF NOT EXISTS session_compressed (
    session_id      TEXT PRIMARY KEY REFERENCES sessions(id),
    compressed_json TEXT NOT NULL,
    raw_log_hash    TEXT NOT NULL
);

-- 04 §4.2 session_metrics (1:1, Phase B, 핵심 시계열, 보존 10년)
CREATE TABLE IF NOT EXISTS session_metrics (
    metric_id           TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL REFERENCES sessions(id),
    student_id          TEXT NOT NULL REFERENCES students(id),
    course_id           TEXT NOT NULL REFERENCES courses(id),
    crp_output          TEXT NOT NULL,
    mti                 REAL,
    qli                 REAL,
    rec                 REAL,
    recon               REAL,
    orc                 REAL,
    qualitative_band_mti TEXT,
    disengagement_flag  INTEGER NOT NULL DEFAULT 0,
    low_reliability     INTEGER NOT NULL DEFAULT 0,
    session_duration_min REAL,
    rubric_version      TEXT NOT NULL,
    prompt_version      TEXT NOT NULL,
    output_hash         TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_metrics_student_course
    ON session_metrics(student_id, course_id, created_at);

-- 04 §4 session_evidence (1:N, LLM 판단 근거, 보존 3년)
CREATE TABLE IF NOT EXISTS session_evidence (
    evidence_id     TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    item_key        TEXT NOT NULL,
    run_index       INTEGER NOT NULL,
    score           INTEGER,
    evidence_text   TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- 04 §4.3 phase_a_results (1:N, Phase A 진단, 보존 5년, session_metrics와 물리적 분리)
CREATE TABLE IF NOT EXISTS phase_a_results (
    profile_id          TEXT PRIMARY KEY,
    student_id          TEXT NOT NULL REFERENCES students(id),
    course_id           TEXT NOT NULL REFERENCES courses(id),
    responses           TEXT NOT NULL,
    qli_axis_score      REAL NOT NULL,
    mti_axis_score      REAL NOT NULL,
    entry_type          TEXT NOT NULL,
    question_pool_version TEXT NOT NULL,
    completed_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- 04 §3 parameter_configs (독립, scope+scope_id 조회, 삭제 금지)
CREATE TABLE IF NOT EXISTS parameter_configs (
    config_id   TEXT PRIMARY KEY,
    scope       TEXT NOT NULL CHECK(scope IN ('institution','department','professor','system')),
    scope_id    TEXT NOT NULL,
    config_json TEXT NOT NULL,
    version     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(scope, scope_id)
);

-- ── v0.5 문항 관리: Phase A 객관식 문항 풀 ─────────────────────────────
CREATE TABLE IF NOT EXISTS question_pool_items (
    item_id      TEXT PRIMARY KEY,
    axis         TEXT NOT NULL CHECK(axis IN ('qli','mti')),
    text         TEXT NOT NULL,
    reverse      INTEGER NOT NULL DEFAULT 0,
    sub_domain   TEXT,
    difficulty   TEXT DEFAULT 'mid' CHECK(difficulty IN ('low','mid','high')),
    active       INTEGER NOT NULL DEFAULT 0,
    pool_version TEXT NOT NULL DEFAULT 'q_f1.0',
    created_by   TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ── v0.5 문항 관리: Phase B PBL 과제 풀 ───────────────────────────────
CREATE TABLE IF NOT EXISTS pbl_tasks (
    task_id        TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    department     TEXT,
    difficulty     TEXT DEFAULT 'mid' CHECK(difficulty IN ('low','mid','high')),
    target_metrics TEXT,             -- JSON 배열: QLI, MTI, Rec, Recon, Orc 등
    trigger_design TEXT,             -- JSON 배열 또는 설명: 인지충돌, 전제도전 등
    questions_json TEXT NOT NULL,    -- JSON 배열: 기본 문항
    advanced_json  TEXT,             -- JSON 배열: 심화 문항
    task_version   TEXT NOT NULL DEFAULT 't_f1.0',
    active         INTEGER NOT NULL DEFAULT 1,
    created_by     TEXT,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ── v0.5 스냅샷: Phase A 응답 당시 문항 보존 ───────────────────────────
CREATE TABLE IF NOT EXISTS session_question_snapshot (
    snapshot_id   TEXT PRIMARY KEY,
    profile_id    TEXT REFERENCES phase_a_results(profile_id),
    session_id    TEXT REFERENCES sessions(id),
    student_id    TEXT NOT NULL,
    course_id     TEXT NOT NULL,
    phase         TEXT NOT NULL DEFAULT 'A',
    snapshot_json TEXT NOT NULL,
    pool_version  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ── v0.5 스냅샷: Phase B 세션 당시 과제 보존 ───────────────────────────
CREATE TABLE IF NOT EXISTS session_task_snapshot (
    snapshot_id   TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    student_id    TEXT NOT NULL,
    course_id     TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    task_version  TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- 09 §3 measure_queue (인프라 테이블, 측정 데이터 아님)
CREATE TABLE IF NOT EXISTS measure_queue (
    job_id          TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL UNIQUE REFERENCES sessions(id),
    status          TEXT NOT NULL DEFAULT 'pending'
                         CHECK(status IN ('pending','processing','done','failed')),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    processed_at    TEXT
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    """전체 스키마 초기화. 멱등(IF NOT EXISTS)."""
    conn.executescript(_DDL)
    conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════════
# session_metrics — 저장·조회
# ════════════════════════════════════════════════════════════════════════

def save_crp_output(conn: sqlite3.Connection, crp_output: dict,
                    course_id: str) -> str:
    """CRP_output을 session_metrics에 저장. metric_id 반환."""
    metric_id = str(uuid.uuid4())
    m = crp_output.get("metrics", {})
    qb = crp_output.get("qualitative_band", {})
    rel = crp_output.get("reliability", {})
    conn.execute("""
        INSERT INTO session_metrics
            (metric_id, session_id, student_id, course_id, crp_output,
             mti, qli, rec, recon, orc, qualitative_band_mti,
             disengagement_flag, low_reliability, session_duration_min,
             rubric_version, prompt_version, output_hash, created_at)
        VALUES (?,?,?,?,?, ?,?,?,?,?,?, ?,?,?, ?,?,?,?)
    """, (
        metric_id, crp_output["session_id"], crp_output["student_id"],
        course_id, json.dumps(crp_output, ensure_ascii=False),
        m.get("MTI"), m.get("QLI"), m.get("Rec"), m.get("Recon"), m.get("Orc"),
        (qb.get("MTI") or {}).get("band"),
        1 if rel.get("disengagement_flag") else 0,
        1 if rel.get("low_reliability") else 0,
        m.get("session_duration_min"),
        crp_output.get("rubric_version", ""),
        crp_output.get("prompt_version", ""),
        crp_output.get("hash", ""),
        _now(),
    ))
    conn.commit()
    return metric_id


def load_metrics_history(conn: sqlite3.Connection, student_id: str,
                         course_id: str, n: int = 10,
                         exclude_disengaged: bool = True) -> list[dict]:
    """Velocity/Grokking 계산용 시계열. 시간순(오래된 것 먼저).
    exclude_disengaged=True: disengagement_flag 세션 제외(02 §3.6, 06 §9)."""
    sql = """
        SELECT crp_output FROM session_metrics
        WHERE student_id=? AND course_id=?
        {}
        ORDER BY created_at ASC
        LIMIT ?
    """.format("AND disengagement_flag=0" if exclude_disengaged else "")
    rows = conn.execute(sql, (student_id, course_id, n)).fetchall()
    return [json.loads(r["crp_output"])["metrics"] for r in rows]


def load_latest_crp_output(conn: sqlite3.Connection, student_id: str,
                            course_id: str) -> Optional[dict]:
    row = conn.execute("""
        SELECT crp_output FROM session_metrics
        WHERE student_id=? AND course_id=?
        ORDER BY created_at DESC LIMIT 1
    """, (student_id, course_id)).fetchone()
    return json.loads(row["crp_output"]) if row else None


# ════════════════════════════════════════════════════════════════════════
# phase_a_results — 저장·조회 (session_metrics와 물리적 분리, 규칙 5)
# ════════════════════════════════════════════════════════════════════════

def save_phase_a(conn: sqlite3.Connection, student_id: str, course_id: str,
                 entry_profile: dict) -> str:
    """Phase A 결과 저장. profile_id 반환. metrics 테이블과 완전 분리(04 §4.3)."""
    profile_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO phase_a_results
            (profile_id, student_id, course_id, responses,
             qli_axis_score, mti_axis_score, entry_type,
             question_pool_version, completed_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        profile_id, student_id, course_id,
        json.dumps(entry_profile.get("responses", []), ensure_ascii=False),
        entry_profile["qli_axis_score"], entry_profile["mti_axis_score"],
        entry_profile["entry_type"],
        entry_profile.get("question_pool_version", "q_f1.0"),
        _now(),
    ))
    conn.commit()
    return profile_id


def load_latest_phase_a(conn: sqlite3.Connection, student_id: str,
                        course_id: str) -> Optional[dict]:
    """최신 Phase A 결과(entry_profile) 반환. 07 §2.2 재시도 정책: 최신만 활성."""
    row = conn.execute("""
        SELECT * FROM phase_a_results
        WHERE student_id=? AND course_id=?
        ORDER BY completed_at DESC LIMIT 1
    """, (student_id, course_id)).fetchone()
    if not row:
        return None
    return {
        "qli_axis_score": row["qli_axis_score"],
        "mti_axis_score": row["mti_axis_score"],
        "entry_type": row["entry_type"],
        "question_pool_version": row["question_pool_version"],
        "profile_id": row["profile_id"],
    }


# ════════════════════════════════════════════════════════════════════════
# measure_queue (09 §3) — push / pop / status 업데이트
# ════════════════════════════════════════════════════════════════════════

def push_measure_queue(conn: sqlite3.Connection, session_id: str) -> str:
    """측정 큐에 작업 추가. job_id 반환. 중복 session_id는 UNIQUE 제약으로 차단."""
    job_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO measure_queue (job_id, session_id, status, created_at)
        VALUES (?, ?, 'pending', ?)
    """, (job_id, session_id, _now()))
    conn.commit()
    return job_id


def pop_measure_queue(conn: sqlite3.Connection) -> Optional[dict]:
    """가장 오래된 pending 작업을 processing으로 전환 후 반환. 없으면 None."""
    row = conn.execute("""
        SELECT job_id, session_id FROM measure_queue
        WHERE status='pending' ORDER BY created_at ASC LIMIT 1
    """).fetchone()
    if not row:
        return None
    conn.execute("""
        UPDATE measure_queue SET status='processing', processed_at=?
        WHERE job_id=?
    """, (_now(), row["job_id"]))
    conn.commit()
    return {"job_id": row["job_id"], "session_id": row["session_id"]}


def update_queue_status(conn: sqlite3.Connection, job_id: str,
                        status: str, increment_retry: bool = False) -> None:
    """큐 작업 상태 업데이트. 실패 시 retry_count 증가."""
    if increment_retry:
        conn.execute("""
            UPDATE measure_queue
            SET status=?, processed_at=?, retry_count=retry_count+1
            WHERE job_id=?
        """, (status, _now(), job_id))
    else:
        conn.execute("""
            UPDATE measure_queue SET status=?, processed_at=? WHERE job_id=?
        """, (status, _now(), job_id))
    conn.commit()


# ════════════════════════════════════════════════════════════════════════
# 보조: sessions, students, courses 최소 CRUD (워커·엔진 필요분)
# ════════════════════════════════════════════════════════════════════════

def upsert_student(conn: sqlite3.Connection, student_id: str,
                   name: str = "") -> None:
    conn.execute("INSERT OR IGNORE INTO students(id,name) VALUES(?,?)",
                 (student_id, name))
    conn.commit()


def upsert_course(conn: sqlite3.Connection, course_id: str,
                  name: str = "", dept: str = "") -> None:
    conn.execute("INSERT OR IGNORE INTO courses(id,name,dept) VALUES(?,?,?)",
                 (course_id, name, dept))
    conn.commit()


def save_session(conn: sqlite3.Connection, session: dict) -> str:
    """sessions 테이블 저장. session_id 반환."""
    sid = session.get("session_id") or str(uuid.uuid4())
    conn.execute("""
        INSERT OR REPLACE INTO sessions
            (id,student_id,course_id,task_id,phase,status,session_start,session_end)
        VALUES (?,?,?,?,?,?,?,?)
    """, (sid, session["student_id"], session["course_id"],
          session.get("task_id"), session.get("phase","B"),
          session.get("status","active"),
          session.get("session_start", _now()), session.get("session_end")))
    conn.commit()
    return sid


def update_session_status(conn: sqlite3.Connection,
                          session_id: str, status: str,
                          session_end: str | None = None) -> None:
    """세션 상태 업데이트. session_end가 주어지면 종료 시각도 함께 기록한다."""
    if session_end is None:
        conn.execute("UPDATE sessions SET status=? WHERE id=?", (status, session_id))
    else:
        conn.execute(
            "UPDATE sessions SET status=?, session_end=? WHERE id=?",
            (status, session_end, session_id),
        )
    conn.commit()


# ════════════════════════════════════════════════════════════════════════
# v0.5 문항 관리 — Phase A 객관식 문항 풀
# ════════════════════════════════════════════════════════════════════════

def _bump_pool_version(conn: sqlite3.Connection) -> str:
    """문항 풀 활성화 버전 증가. q_f1.0 → q_f1.1 형식."""
    cur = get_pool_version(conn)
    m = __import__("re").match(r"^(.*\.)(\d+)$", cur)
    nxt = f"{m.group(1)}{int(m.group(2)) + 1}" if m else f"{cur}.1"
    conn.execute("""
        INSERT INTO parameter_configs(config_id,scope,scope_id,config_json,version,created_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(scope,scope_id) DO UPDATE
        SET config_json=excluded.config_json, version=excluded.version
    """, (str(uuid.uuid4()), "system", "pool_version",
          json.dumps({"v": nxt}, ensure_ascii=False), nxt, _now()))
    conn.commit()
    return nxt


def get_pool_version(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT config_json FROM parameter_configs WHERE scope='system' AND scope_id='pool_version'"
    ).fetchone()
    return json.loads(row["config_json"]).get("v", "q_f1.0") if row else "q_f1.0"


def init_question_pool_if_empty(conn: sqlite3.Connection, json_path: str) -> None:
    """DB 문항 풀이 비어 있을 때만 config/question_pool.json에서 초기화한다."""
    if conn.execute("SELECT COUNT(*) FROM question_pool_items").fetchone()[0]:
        return
    try:
        with open(json_path, encoding="utf-8") as f:
            pool = json.load(f)
    except FileNotFoundError:
        return
    version = pool.get("version", "q_f1.0")
    for item in pool.get("items", []):
        conn.execute("""
            INSERT OR IGNORE INTO question_pool_items
                (item_id,axis,text,reverse,sub_domain,difficulty,active,pool_version,created_by)
            VALUES(?,?,?,?,?,?,?,?,?)
        """, (
            item["item_id"], item["axis"], item["text"],
            1 if item.get("reverse") else 0,
            item.get("sub_domain"), item.get("difficulty", "mid"),
            1 if item.get("active") else 0, version, "seed_json",
        ))
    conn.execute("""
        INSERT OR IGNORE INTO parameter_configs(config_id,scope,scope_id,config_json,version,created_at)
        VALUES(?,?,?,?,?,?)
    """, (str(uuid.uuid4()), "system", "pool_version",
          json.dumps({"v": version}, ensure_ascii=False), version, _now()))
    conn.commit()


def get_all_question_items(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM question_pool_items ORDER BY axis, active DESC, item_id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_items(conn: sqlite3.Connection, axis: str | None = None) -> list[dict]:
    if axis:
        rows = conn.execute(
            "SELECT * FROM question_pool_items WHERE axis=? AND active=1 ORDER BY item_id", (axis,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM question_pool_items WHERE active=1 ORDER BY axis, item_id"
        ).fetchall()
    return [dict(r) for r in rows]


def add_question_item(conn: sqlite3.Connection, item: dict, created_by: str = "") -> str:
    """신규 문항 추가. 기본 상태는 대기(active=0)."""
    axis = item["axis"].lower()
    item_id = item.get("item_id") or f"{axis.upper()}_{str(uuid.uuid4())[:8].upper()}"
    conn.execute("""
        INSERT INTO question_pool_items
            (item_id,axis,text,reverse,sub_domain,difficulty,active,pool_version,created_by)
        VALUES(?,?,?,?,?,?,0,?,?)
    """, (
        item_id, axis, item["text"], 1 if item.get("reverse") else 0,
        item.get("sub_domain"), item.get("difficulty", "mid"),
        get_pool_version(conn), created_by,
    ))
    conn.commit()
    return item_id


def activate_question_item(conn: sqlite3.Connection, item_id: str) -> tuple[bool, str]:
    """문항 활성화. 활성화 시 풀 버전을 증가시킨다."""
    row = conn.execute("SELECT item_id FROM question_pool_items WHERE item_id=?", (item_id,)).fetchone()
    if not row:
        return False, "문항을 찾을 수 없습니다."
    new_ver = _bump_pool_version(conn)
    conn.execute(
        "UPDATE question_pool_items SET active=1, pool_version=?, updated_at=? WHERE item_id=?",
        (new_ver, _now(), item_id),
    )
    conn.commit()
    return True, new_ver


def deactivate_question_item(conn: sqlite3.Connection, item_id: str) -> None:
    """문항 삭제 대신 비활성화한다. 과거 스냅샷은 유지된다."""
    conn.execute(
        "UPDATE question_pool_items SET active=0, updated_at=? WHERE item_id=?",
        (_now(), item_id),
    )
    conn.commit()


def check_pool_constraints(conn: sqlite3.Connection) -> dict:
    qli_active = conn.execute(
        "SELECT COUNT(*) FROM question_pool_items WHERE axis='qli' AND active=1"
    ).fetchone()[0]
    mti_active = conn.execute(
        "SELECT COUNT(*) FROM question_pool_items WHERE axis='mti' AND active=1"
    ).fetchone()[0]
    qli_rev = conn.execute(
        "SELECT COUNT(*) FROM question_pool_items WHERE axis='qli' AND active=1 AND reverse=1"
    ).fetchone()[0]
    mti_rev = conn.execute(
        "SELECT COUNT(*) FROM question_pool_items WHERE axis='mti' AND active=1 AND reverse=1"
    ).fetchone()[0]
    warnings = []
    if qli_active < 5:
        warnings.append("QLI 활성 문항 5개 미만 — Phase A 진단 불가")
    if mti_active < 5:
        warnings.append("MTI 활성 문항 5개 미만 — Phase A 진단 불가")
    if qli_rev == 0:
        warnings.append("QLI 역문항 없음 — 응답 편향 점검 약화")
    if mti_rev == 0:
        warnings.append("MTI 역문항 없음 — 응답 편향 점검 약화")
    return {
        "qli_active": qli_active,
        "mti_active": mti_active,
        "qli_reverse": qli_rev,
        "mti_reverse": mti_rev,
        "phase_a_ready": qli_active >= 5 and mti_active >= 5,
        "warnings": warnings,
    }


# ════════════════════════════════════════════════════════════════════════
# v0.5 문항 관리 — Phase B PBL 과제 풀
# ════════════════════════════════════════════════════════════════════════

def init_pbl_tasks_if_empty(conn: sqlite3.Connection, json_path: str) -> None:
    if conn.execute("SELECT COUNT(*) FROM pbl_tasks").fetchone()[0]:
        return
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return
    for t in data.get("tasks", []):
        conn.execute("""
            INSERT OR IGNORE INTO pbl_tasks
                (task_id,title,department,difficulty,target_metrics,trigger_design,
                 questions_json,advanced_json,task_version,active,created_by)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            t["task_id"], t["title"], t.get("department"), t.get("difficulty", "mid"),
            json.dumps(t.get("target_metrics", []), ensure_ascii=False),
            json.dumps(t.get("trigger_design", []), ensure_ascii=False),
            json.dumps(t.get("questions", []), ensure_ascii=False),
            json.dumps(t.get("advanced_questions", []), ensure_ascii=False),
            t.get("task_version", data.get("version", "t_f1.0")),
            1 if t.get("active", True) else 0,
            "seed_json",
        ))
    conn.commit()


def _task_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["questions"] = json.loads(d.pop("questions_json") or "[]")
    d["advanced_questions"] = json.loads(d.pop("advanced_json") or "[]")
    d["target_metrics"] = json.loads(d.get("target_metrics") or "[]")
    d["trigger_design"] = json.loads(d.get("trigger_design") or "[]")
    return d


def get_all_pbl_tasks(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM pbl_tasks ORDER BY active DESC, department, task_id"
    ).fetchall()
    return [_task_row_to_dict(r) for r in rows]


def get_active_pbl_tasks(conn: sqlite3.Connection, dept: str | None = None) -> list[dict]:
    if dept:
        rows = conn.execute(
            "SELECT * FROM pbl_tasks WHERE active=1 AND (department=? OR department IS NULL) ORDER BY department, task_id",
            (dept,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pbl_tasks WHERE active=1 ORDER BY department, task_id").fetchall()
    return [_task_row_to_dict(r) for r in rows]


def get_pbl_task(conn: sqlite3.Connection, task_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM pbl_tasks WHERE task_id=?", (task_id,)).fetchone()
    return _task_row_to_dict(row) if row else None


def add_pbl_task(conn: sqlite3.Connection, task: dict, created_by: str = "") -> str:
    task_id = task.get("task_id") or f"pbl_{str(uuid.uuid4())[:8]}"
    conn.execute("""
        INSERT INTO pbl_tasks
            (task_id,title,department,difficulty,target_metrics,trigger_design,
             questions_json,advanced_json,task_version,active,created_by)
        VALUES(?,?,?,?,?,?,?,?,?,1,?)
    """, (
        task_id, task["title"], task.get("department"), task.get("difficulty", "mid"),
        json.dumps(task.get("target_metrics", []), ensure_ascii=False),
        json.dumps(task.get("trigger_design", []), ensure_ascii=False),
        json.dumps(task.get("questions", []), ensure_ascii=False),
        json.dumps(task.get("advanced_questions", []), ensure_ascii=False),
        task.get("task_version", "t_f1.0"), created_by,
    ))
    conn.commit()
    return task_id


def update_pbl_task(conn: sqlite3.Connection, task_id: str, updates: dict) -> None:
    fields, vals = [], []
    mapping = {
        "title": "title",
        "department": "department",
        "difficulty": "difficulty",
        "task_version": "task_version",
    }
    for key, col in mapping.items():
        if key in updates:
            fields.append(f"{col}=?")
            vals.append(updates[key])
    json_mapping = {
        "target_metrics": "target_metrics",
        "trigger_design": "trigger_design",
        "questions": "questions_json",
        "advanced_questions": "advanced_json",
    }
    for key, col in json_mapping.items():
        if key in updates:
            fields.append(f"{col}=?")
            vals.append(json.dumps(updates[key], ensure_ascii=False))
    if not fields:
        return
    fields.append("updated_at=?")
    vals.append(_now())
    vals.append(task_id)
    conn.execute(f"UPDATE pbl_tasks SET {', '.join(fields)} WHERE task_id=?", vals)
    conn.commit()


def toggle_pbl_task_active(conn: sqlite3.Connection, task_id: str, active: bool) -> None:
    conn.execute(
        "UPDATE pbl_tasks SET active=?, updated_at=? WHERE task_id=?",
        (1 if active else 0, _now(), task_id),
    )
    conn.commit()


# ════════════════════════════════════════════════════════════════════════
# v0.5 스냅샷 저장
# ════════════════════════════════════════════════════════════════════════

def save_phase_a_question_snapshot(conn: sqlite3.Connection, profile_id: str,
                                   student_id: str, course_id: str,
                                   questions: list[dict], pool_version: str) -> str:
    snapshot_id = str(uuid.uuid4())
    conn.execute("""
        INSERT INTO session_question_snapshot
            (snapshot_id,profile_id,student_id,course_id,phase,snapshot_json,pool_version,created_at)
        VALUES(?,?,?,?,?,?,?,?)
    """, (
        snapshot_id, profile_id, student_id, course_id, "A",
        json.dumps(questions, ensure_ascii=False), pool_version, _now(),
    ))
    conn.commit()
    return snapshot_id


def save_session_task_snapshot(conn: sqlite3.Connection, session_id: str,
                               student_id: str, course_id: str, task: dict) -> str:
    snapshot_id = str(uuid.uuid4())
    conn.execute("""
        INSERT OR REPLACE INTO session_task_snapshot
            (snapshot_id,session_id,student_id,course_id,task_id,snapshot_json,task_version,created_at)
        VALUES(?,?,?,?,?,?,?,?)
    """, (
        snapshot_id, session_id, student_id, course_id, task["task_id"],
        json.dumps(task, ensure_ascii=False), task.get("task_version", "t_f1.0"), _now(),
    ))
    conn.commit()
    return snapshot_id
