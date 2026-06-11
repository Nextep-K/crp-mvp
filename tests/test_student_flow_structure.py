from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_routes_students_to_continuous_flow():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "pages._student_flow" in app
    assert "Phase A 진단", "Phase B 세션" not in app
    assert "student_flow_view" in app


def test_student_flow_preserves_phase_separation_language():
    flow = (ROOT / "pages" / "_student_flow.py").read_text(encoding="utf-8")
    assert "Phase A 결과" in flow
    assert "합산되지 않습니다" in flow
    assert "db.save_phase_a" in flow
    assert "_phase_b.render" in flow


def test_phase_b_uses_package_imports_for_llm_components():
    phase_b = (ROOT / "pages" / "_phase_b.py").read_text(encoding="utf-8")
    assert "engines.phase_b_engine.llm_client" in phase_b
    assert "from engines.phase_b_engine import prompts" in phase_b
