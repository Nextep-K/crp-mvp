"""Admin content management feature block."""
from __future__ import annotations


def render(conn, prof_id: str, course_id: str) -> None:
    from pages._question_pool import render as render_question_pool

    render_question_pool(conn, prof_id, course_id)
