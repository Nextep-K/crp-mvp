import json
import sqlite3

import db
import phase_a_engine as PA
import report_merger as RM
import compute_module as A


def new_conn():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    db.init_schema(conn)
    db.upsert_student(conn, "u1")
    db.upsert_course(conn, "c1", "한국사", "history")
    return conn


def make_crp(sid="s1", mti=7.0, qli=6.0, disengaged=False):
    return A.assemble_crp_output(
        session_id=sid, student_id="u1",
        metrics={"MTI": mti, "QLI": qli, "Rec": 7, "Recon": 7, "Orc": 7, "session_duration_min": 30},
        reliability={"disengagement_flag": disengaged, "low_reliability": False},
        params_applied={"institution": "BNU"},
    )


def test_db_schema_phase_a_b_separation_and_history():
    conn = new_conn()
    db.save_session(conn, {"session_id":"s1","student_id":"u1","course_id":"c1","phase":"B","status":"measured","session_start":"2026-04-01T00:00:00Z"})
    db.save_crp_output(conn, make_crp("s1", 7, 6), "c1")
    db.save_session(conn, {"session_id":"s2","student_id":"u1","course_id":"c1","phase":"B","status":"measured","session_start":"2026-04-02T00:00:00Z"})
    db.save_crp_output(conn, make_crp("s2", 3, 2, disengaged=True), "c1")
    assert len(db.load_metrics_history(conn, "u1", "c1", exclude_disengaged=True)) == 1
    assert len(db.load_metrics_history(conn, "u1", "c1", exclude_disengaged=False)) == 2

    responses = [
        {"item_id": f"QLI_{i}", "axis":"qli", "score":3, "reverse": i == 1} for i in range(5)
    ] + [
        {"item_id": f"MTI_{i}", "axis":"mti", "score":3, "reverse": i == 1} for i in range(5)
    ]
    ep = PA.phase_a_score(responses)
    assert ep["entry_type"] in PA.TYPE_NAMES
    db.save_phase_a(conn, "u1", "c1", ep)
    assert db.load_latest_phase_a(conn, "u1", "c1")["entry_type"] == ep["entry_type"]

    a_cols = {r[1] for r in conn.execute("PRAGMA table_info(phase_a_results)")}
    m_cols = {r[1] for r in conn.execute("PRAGMA table_info(session_metrics)")}
    assert len(a_cols & m_cols - {"student_id", "course_id"}) == 0


def test_report_merger_no_combined_score_fields():
    ep = {"qli_axis_score": 6, "mti_axis_score": 5, "entry_type": "상상가형"}
    report = RM.generate_final_report(ep, [{"QLI": 7, "MTI": 6, "Rec": 5, "Recon": 6, "Orc": 5}])
    blob = json.dumps(report, ensure_ascii=False)
    for banned in ["weighted_sum", "combined_score", "unified_index", "total_score", "final_combined_score"]:
        assert banned not in blob
    assert "self_vs_behavior_gap" in blob
