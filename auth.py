"""경량 파일럿 접근 제어 유틸리티.

사용자 명단 검증 없이, 공통 참여 코드와 관리자 비밀번호를 Streamlit Secrets/환경변수에서 읽는다.
"""
from __future__ import annotations

import os
from typing import Any, Mapping


DEFAULT_STUDENT_ACCESS_CODE = "pilot2026"


def _read_secret(secrets: Any, key: str) -> str:
    if secrets is None:
        return ""
    try:
        value = secrets.get(key, "")
    except Exception:
        return ""
    return str(value or "")


def get_student_access_code(secrets: Any = None, environ: Mapping[str, str] | None = None) -> str:
    """학생 공통 참여 코드를 반환한다.

    우선순위:
    1. Streamlit secrets["STUDENT_ACCESS_CODE"]
    2. 환경변수 STUDENT_ACCESS_CODE
    3. 로컬 MVP 기본값 pilot2026
    """
    env = environ if environ is not None else os.environ
    return _read_secret(secrets, "STUDENT_ACCESS_CODE") or env.get("STUDENT_ACCESS_CODE", "") or DEFAULT_STUDENT_ACCESS_CODE


def validate_student_access_code(provided: str, expected: str) -> bool:
    """공백 제거 후 학생 참여 코드 일치 여부를 판정한다."""
    return bool(provided and expected and provided.strip() == expected.strip())


def privacy_notice() -> str:
    return (
        "검증 파일럿용 로그인입니다. 실명, 주민등록번호, 전화번호 등 민감한 개인정보를 입력하지 말고 "
        "테스트용 닉네임 또는 임시 ID를 사용하세요."
    )
