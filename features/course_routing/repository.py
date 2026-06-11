"""SQLite repository for the course routing feature block.

이 모듈은 기존 storage/db.py에 기능 함수를 계속 추가하지 않기 위한
adapter/repository 계층이다. 기존 courses 테이블과 병행해 course_routes를
독립 관리한다.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .models import make_course_id, normalize_college_code, normalize_department_code, normalize_subject_code


DDL = """
CREATE TABLE IF NOT EXISTS course_routes (
    course_id        TEXT PRIMARY KEY,
    college_code     TEXT NOT NULL CHECK(length(college_code)=1),
    college_name     TEXT NOT NULL,
    department_code  TEXT NOT NULL CHECK(length(department_code)=2),
    department_name  TEXT NOT NULL,
    subject_code     TEXT NOT NULL CHECK(length(subject_code)=6),
    course_name      TEXT NOT NULL,
    professor_name   TEXT,
    active           INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(college_code, department_code, subject_code)
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()


def seed_default_if_empty(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT COUNT(*) FROM course_routes").fetchone()
    if row and row[0] > 0:
        return
    upsert_course_route(conn, {
        "college_code": "A",
        "college_name": "기본 단과대학",
        "department_code": "00",
        "department_name": "공통 학과",
        "subject_code": "CRP001",
        "course_name": "CRP 기본 파일럿",
        "professor_name": "관리자",
        "active": True,
    })


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def upsert_course_route(conn: sqlite3.Connection, route: dict) -> str:
    college_code = normalize_college_code(route["college_code"])
    department_code = normalize_department_code(route["department_code"])
    subject_code = normalize_subject_code(route["subject_code"])
    course_id = make_course_id(college_code, department_code, subject_code)
    conn.execute(
        """
        INSERT INTO course_routes
            (course_id, college_code, college_name, department_code, department_name,
             subject_code, course_name, professor_name, active, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        ON CONFLICT(course_id) DO UPDATE SET
            college_name=excluded.college_name,
            department_name=excluded.department_name,
            course_name=excluded.course_name,
            professor_name=excluded.professor_name,
            active=excluded.active,
            updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
        """,
        (
            course_id,
            college_code,
            route["college_name"].strip(),
            department_code,
            route["department_name"].strip(),
            subject_code,
            route["course_name"].strip(),
            (route.get("professor_name") or "").strip(),
            1 if route.get("active", True) else 0,
        ),
    )
    conn.execute(
        "INSERT OR IGNORE INTO courses(id, name, dept) VALUES (?, ?, ?)",
        (course_id, route["course_name"].strip(), route["department_name"].strip()),
    )
    conn.commit()
    return course_id


def list_course_routes(conn: sqlite3.Connection, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM course_routes"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY college_code, department_code, subject_code"
    rows = conn.execute(sql).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_course_route(conn: sqlite3.Connection, course_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM course_routes WHERE course_id=?", (course_id,)).fetchone()
    return _row_to_dict(row) if row else None


def set_course_route_active(conn: sqlite3.Connection, course_id: str, active: bool) -> None:
    conn.execute(
        "UPDATE course_routes SET active=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE course_id=?",
        (1 if active else 0, course_id),
    )
    conn.commit()


def list_colleges(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT college_code, college_name, COUNT(*) AS course_count
        FROM course_routes
        WHERE active=1
        GROUP BY college_code, college_name
        ORDER BY college_code
        """
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_departments(conn: sqlite3.Connection, college_code: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT department_code, department_name, COUNT(*) AS course_count
        FROM course_routes
        WHERE active=1 AND college_code=?
        GROUP BY department_code, department_name
        ORDER BY department_code
        """,
        (normalize_college_code(college_code),),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_courses(conn: sqlite3.Connection, college_code: str, department_code: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM course_routes
        WHERE active=1 AND college_code=? AND department_code=?
        ORDER BY subject_code
        """,
        (normalize_college_code(college_code), normalize_department_code(department_code)),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]
