from __future__ import annotations

from auth import DEFAULT_STUDENT_ACCESS_CODE, get_student_access_code, privacy_notice, validate_student_access_code


def test_student_access_code_defaults_to_pilot_code():
    assert get_student_access_code(secrets={}, environ={}) == DEFAULT_STUDENT_ACCESS_CODE


def test_student_access_code_prefers_secrets_over_env():
    assert get_student_access_code(secrets={"STUDENT_ACCESS_CODE": "secret-code"}, environ={"STUDENT_ACCESS_CODE": "env-code"}) == "secret-code"


def test_student_access_code_can_use_env():
    assert get_student_access_code(secrets={}, environ={"STUDENT_ACCESS_CODE": "env-code"}) == "env-code"


def test_validate_student_access_code():
    assert validate_student_access_code(" pilot2026 ", "pilot2026")
    assert not validate_student_access_code("wrong", "pilot2026")
    assert not validate_student_access_code("", "pilot2026")


def test_privacy_notice_warns_against_sensitive_personal_data():
    notice = privacy_notice()
    assert "주민등록번호" in notice
    assert "전화번호" in notice
    assert "테스트용" in notice
