# CRP v0.5 Deployment Checklist

## Repository root
이 폴더의 내용물을 GitHub 저장소 루트에 올립니다.

필수 파일:
- `app.py`
- `requirements.txt`
- `storage/db.py`
- `pages/*.py`
- `engines/`
- `config/`

## Streamlit Cloud
- Main file path: `app.py`
- Secrets:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
PROF_PASSWORD = "관리자비밀번호"
STUDENT_ACCESS_CODE = "파일럿참여코드"
```

## Do not commit
- `.streamlit/secrets.toml`
- `storage/data.db`
- `__pycache__/`
- `.pytest_cache/`

## Note
Streamlit Community Cloud의 로컬 SQLite 파일은 재배포/재시작 시 초기화될 수 있습니다.
파일럿 클릭 흐름 검증용으로 사용하고, 장기 운영은 외부 DB 전환이 필요합니다.
