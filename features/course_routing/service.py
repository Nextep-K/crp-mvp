"""Service layer for course routing.

UI and persistence validation/init logic.
"""
from __future__ import annotations

import sqlite3

from . import repository
from .models import validate_codes


DEFAULT_DEMO_COURSE_ID = "A00CRP001"
DEFAULT_DEMO_TASK_ID = "pbl_common_01"


def init_course_routing(conn: sqlite3.Connection) -> None:
    repository.init_schema(conn)
    repository.seed_default_if_empty(conn)
    ensure_default_demo_task_route(conn)


def ensure_default_demo_task_route(conn: sqlite3.Connection) -> None:
    """Give the default demo course an explicit active Phase B task route.

    If an active route already exists, keep the operator-selected route.
    """
    route = repository.get_course_route(conn, DEFAULT_DEMO_COURSE_ID)
    if route is None:
        routes = repository.list_course_routes(conn, active_only=True)
        route = routes[0] if routes else None
    if route is None:
        return

    course_id = route["course_id"]
    existing = conn.execute(
        "SELECT 1 FROM course_task_routes WHERE course_id=? AND active=1 LIMIT 1",
        (course_id,),
    ).fetchone()
    if existing:
        return

    task = conn.execute(
        """
        SELECT task_id
        FROM pbl_tasks
        WHERE active=1
        ORDER BY
            CASE
                WHEN task_id=? THEN 0
                WHEN department IS NULL THEN 1
                ELSE 2
            END,
            task_id
        LIMIT 1
        """,
        (DEFAULT_DEMO_TASK_ID,),
    ).fetchone()
    if not task:
        return

    repository.set_course_task_route(conn, course_id, task["task_id"], active=True)


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
    route = repository.get_course_route(conn, DEFAULT_DEMO_COURSE_ID)
    if route and route.get("active"):
        return route
    routes = repository.list_course_routes(conn, active_only=True)
    return routes[0] if routes else None
