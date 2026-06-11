# CRP Pilot MVP v0.4.1

Streamlit 기반 CRP 측정 엔진 MVP입니다.

## 실행

```bash
cd crp_project/crp_pilot
python -m pytest -q
streamlit run app.py
```

## 구조

- `engines/phase_b_engine/compute_module.py`: 모듈 A, 결정론 연산. LLM 호출 금지.
- `engines/phase_b_engine/judgment_module.py`: 모듈 B, LLM 판단. Mock 테스트 우선.
- `engines/phase_a_engine.py`: Phase A 자기 인식 진단.
- `engines/report_merger.py`: Phase A/B 병렬 리포트 결합. 합산 금지.
- `storage/db.py`: SQLite + WAL 저장 계층.
- `workers/measure_worker.py`: 측정 큐 워커.
- `pages/`: 학생/교수 Streamlit 화면.

## v0.2 변경

업로드된 22개 파일을 `09_MVP` 구조에 맞춰 재배치하고, 누락된 Phase A 엔진, 리포트 병합기, Phase B 오케스트레이터, pytest 테스트를 추가했습니다.


## v0.4.1 변경

- 파일럿용 경량 접근 제어를 추가했습니다.
- 학생 로그인에 `STUDENT_ACCESS_CODE` 기반 참여 코드 검증을 추가했습니다.
- 교수 로그인은 기존처럼 `PROF_PASSWORD` 기반으로 유지합니다.
- 로그인 화면에 개인정보 입력 금지 안내를 추가했습니다.
- 사용자 명단 검증, 실명 인증, 휴대폰 인증은 포함하지 않습니다.

## Streamlit Secrets 예시

```toml
ANTHROPIC_API_KEY = ""
PROF_PASSWORD = "관리자비밀번호"
STUDENT_ACCESS_CODE = "파일럿참여코드"
```
