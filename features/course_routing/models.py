"""Course routing data model helpers.

과목 라우팅 코드는 다음 세 요소를 결합한다.
- college_code: A~Z
- department_code: 00~99
- subject_code: 6자리 영문+숫자

course_id = COLLEGE-DEPARTMENT-SUBJECT 형식으로 생성한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

COLLEGE_RE = re.compile(r"^[A-Z]$")
DEPARTMENT_RE = re.compile(r"^[0-9]{2}$")
SUBJECT_RE = re.compile(r"^[A-Z0-9]{6}$")


@dataclass(frozen=True)
class CourseRoute:
    college_code: str
    college_name: str
    department_code: str
    department_name: str
    subject_code: str
    course_name: str
    professor_name: str = ""
    active: bool = True

    @property
    def course_id(self) -> str:
        return make_course_id(self.college_code, self.department_code, self.subject_code)


def normalize_college_code(value: str) -> str:
    return (value or "").strip().upper()


def normalize_department_code(value: str) -> str:
    raw = str(value or "").strip()
    return raw.zfill(2) if raw.isdigit() else raw


def normalize_subject_code(value: str) -> str:
    return (value or "").strip().upper()


def make_course_id(college_code: str, department_code: str, subject_code: str) -> str:
    return f"{normalize_college_code(college_code)}-{normalize_department_code(department_code)}-{normalize_subject_code(subject_code)}"


def validate_codes(college_code: str, department_code: str, subject_code: str) -> tuple[bool, str]:
    college = normalize_college_code(college_code)
    department = normalize_department_code(department_code)
    subject = normalize_subject_code(subject_code)
    if not COLLEGE_RE.match(college):
        return False, "단과대학 코드는 A~Z 한 글자여야 합니다."
    if not DEPARTMENT_RE.match(department):
        return False, "학과 코드는 00~99 두 자리 숫자여야 합니다."
    if not SUBJECT_RE.match(subject):
        return False, "과목 코드는 6자리 영문 대문자/숫자 조합이어야 합니다."
    return True, ""
