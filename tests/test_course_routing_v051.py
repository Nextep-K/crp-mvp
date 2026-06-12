import sqlite3
from pathlib import Path

import db
from features.course_routing import repository, service
from features.course_routing.models import make_course_id, validate_codes

ROOT = Path(__file__).resolve().parents[1]


def new_conn():
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    db.init_schema(conn)
    db.init_question_pool_if_empty(conn, str(ROOT / 'config' / 'question_pool.json'))
    db.init_pbl_tasks_if_empty(conn, str(ROOT / 'config' / 'pbl_tasks.json'))
    service.init_course_routing(conn)
    return conn


def test_course_id_and_validation_rules():
    assert make_course_id('a', '3', 'his101') == 'A-03-HIS101'
    assert validate_codes('A', '03', 'HIS101')[0] is True
    assert validate_codes('AA', '03', 'HIS101')[0] is False
    assert validate_codes('A', '3A', 'HIS101')[0] is False
    assert validate_codes('A', '03', 'HIS10')[0] is False


def test_default_route_is_seeded_and_selectable():
    conn = new_conn()
    routes = repository.list_course_routes(conn, active_only=True)
    assert len(routes) == 1
    assert routes[0]['course_id'] == 'A-00-CRP001'
    assert repository.list_colleges(conn)[0]['college_code'] == 'A'
    assert repository.list_departments(conn, 'A')[0]['department_code'] == '00'
    assert repository.list_courses(conn, 'A', '00')[0]['subject_code'] == 'CRP001'


def test_admin_can_add_update_and_disable_course_route():
    conn = new_conn()
    ok, course_id = service.save_course_route(conn, {
        'college_code': 'B',
        'college_name': '사회과학대학',
        'department_code': '12',
        'department_name': '정책학과',
        'subject_code': 'POL101',
        'course_name': 'AI와 정책 설계',
        'professor_name': '김교수',
        'active': True,
    })
    assert ok is True
    assert course_id == 'B-12-POL101'
    saved = repository.get_course_route(conn, course_id)
    assert saved['course_name'] == 'AI와 정책 설계'

    repository.set_course_route_active(conn, course_id, False)
    assert repository.get_course_route(conn, course_id)['active'] == 0
    assert not any(c['course_id'] == course_id for c in repository.list_courses(conn, 'B', '12'))


def test_phase_b_task_can_be_routed_by_course_id():
    conn = new_conn()
    ok, course_id = service.save_course_route(conn, {
        'college_code': 'C',
        'college_name': '디자인대학',
        'department_code': '07',
        'department_name': '공간디자인학과',
        'subject_code': 'DES301',
        'course_name': 'AI 공간기획',
        'professor_name': '관리자',
        'active': True,
    })
    assert ok is True
    task = db.get_active_pbl_tasks(conn)[0]
    assert repository.get_active_pbl_tasks_for_course(conn, course_id) == []

    repository.set_course_task_route(conn, course_id, task['task_id'], active=True)
    routed = repository.get_active_pbl_tasks_for_course(conn, course_id)
    assert len(routed) == 1
    assert routed[0]['task_id'] == task['task_id']

    repository.set_course_task_route(conn, course_id, task['task_id'], active=False)
    assert repository.get_active_pbl_tasks_for_course(conn, course_id) == []
