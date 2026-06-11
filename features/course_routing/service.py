"""Service layer for course routing.

UI와 저장소 사이의 검증/초기화 로직을 모은다.
"""
from __future__ import annotations

import sqlite3

from . import repository
from .models import validate_codes


def init_course_routing(conn: sqlite3.Connection) -> None:
    repository.init_schema(conn)
    repository.seed_default_if_empty(conn)


def save_course_route(conn: sqlite3.Connection, route: dict) -> tuple[bool, str]:
    ok, msg = validate_codes(
        route.get("college_code", ""),
        route.get("department_code", ""),
        route.get("subject_code", ""),
    )
    if not ok:
        return False, msg
    for key, label in [
        ("college_name", "단과대학명"),
        ("department_name", "학과명"),
        ("course_name", "과목명"),
    ]:
        if not (route.get(key) or "").strip():
            return False, f"{label}을 입력하세요."
    course_id = repository.upsert_course_route(conn, route)
    return True, course_id


def get_default_course(conn: sqlite3.Connection) -> dict | None:
    routes = repository.list_course_routes(conn, active_only=True)
    return routes[0] if routes else None
