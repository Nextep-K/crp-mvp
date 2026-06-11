import json
import sqlite3
from pathlib import Path

import db

ROOT = Path(__file__).resolve().parents[1]


def new_conn():
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    db.init_schema(conn)
    db.init_question_pool_if_empty(conn, str(ROOT / 'config' / 'question_pool.json'))
    db.init_pbl_tasks_if_empty(conn, str(ROOT / 'config' / 'pbl_tasks.json'))
    return conn


def test_question_pool_initializes_from_json_and_constraints():
    conn = new_conn()
    items = db.get_all_question_items(conn)
    assert len([i for i in items if i['axis'] == 'qli']) >= 5
    assert len([i for i in items if i['axis'] == 'mti']) >= 5
    c = db.check_pool_constraints(conn)
    assert c['phase_a_ready'] is True
    assert db.get_pool_version(conn).startswith('q_f1')


def test_question_item_add_activate_deactivate_versioning():
    conn = new_conn()
    before = db.get_pool_version(conn)
    item_id = db.add_question_item(conn, {
        'axis': 'qli',
        'text': '새로운 전제 점검 문항입니다.',
        'reverse': False,
        'difficulty': 'high',
        'sub_domain': 'lp',
    }, created_by='prof_test')
    added = next(i for i in db.get_all_question_items(conn) if i['item_id'] == item_id)
    assert added['active'] == 0

    ok, after = db.activate_question_item(conn, item_id)
    assert ok is True
    assert after != before
    assert next(i for i in db.get_all_question_items(conn) if i['item_id'] == item_id)['active'] == 1

    db.deactivate_question_item(conn, item_id)
    assert next(i for i in db.get_all_question_items(conn) if i['item_id'] == item_id)['active'] == 0


def test_pbl_task_crud_and_active_filter():
    conn = new_conn()
    tasks = db.get_all_pbl_tasks(conn)
    assert len(tasks) >= 1
    tid = db.add_pbl_task(conn, {
        'title': '테스트 PBL 과제',
        'department': None,
        'difficulty': 'mid',
        'target_metrics': ['QLI', 'MTI'],
        'trigger_design': ['인지 충돌'],
        'questions': ['기본 질문 1', '기본 질문 2'],
        'advanced_questions': ['심화 질문 1'],
    }, created_by='prof_test')
    t = db.get_pbl_task(conn, tid)
    assert t['title'] == '테스트 PBL 과제'
    assert len(t['questions']) == 2
    assert t['target_metrics'] == ['QLI', 'MTI']

    db.update_pbl_task(conn, tid, {'title': '수정된 PBL 과제', 'questions': ['수정 질문']})
    assert db.get_pbl_task(conn, tid)['title'] == '수정된 PBL 과제'
    assert db.get_pbl_task(conn, tid)['questions'] == ['수정 질문']

    db.toggle_pbl_task_active(conn, tid, False)
    assert not any(t['task_id'] == tid for t in db.get_active_pbl_tasks(conn))
    assert db.get_pbl_task(conn, tid) is not None


def test_snapshots_preserve_question_and_task_content():
    conn = new_conn()
    db.upsert_student(conn, 'student_v05')
    db.upsert_course(conn, 'course_v05')
    questions = db.get_active_items(conn)[:10]
    profile_id = db.save_phase_a(conn, 'student_v05', 'course_v05', {
        'responses': [],
        'qli_axis_score': 6.0,
        'mti_axis_score': 6.0,
        'entry_type': '설계자형',
        'question_pool_version': db.get_pool_version(conn),
    })
    snap_id = db.save_phase_a_question_snapshot(
        conn, profile_id, 'student_v05', 'course_v05', questions, db.get_pool_version(conn)
    )
    row = conn.execute('SELECT snapshot_json FROM session_question_snapshot WHERE snapshot_id=?', (snap_id,)).fetchone()
    assert row is not None
    assert json.loads(row['snapshot_json'])[0]['text'] == questions[0]['text']

    task = db.get_active_pbl_tasks(conn)[0]
    session_id = db.save_session(conn, {
        'student_id': 'student_v05',
        'course_id': 'course_v05',
        'task_id': task['task_id'],
        'phase': 'B',
        'status': 'active',
    })
    tsnap_id = db.save_session_task_snapshot(conn, session_id, 'student_v05', 'course_v05', task)
    trow = conn.execute('SELECT snapshot_json FROM session_task_snapshot WHERE snapshot_id=?', (tsnap_id,)).fetchone()
    assert trow is not None
    assert json.loads(trow['snapshot_json'])['task_id'] == task['task_id']
