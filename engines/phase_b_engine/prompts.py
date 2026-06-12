"""
prompts.py — 모듈 B LLM 프롬프트 (05_프롬프트_v_f1, p_f1.0)

캐노니컬은 02_루브릭. 프롬프트는 루브릭의 운영 파생물이며 충돌 시 02 우선.
시스템 프롬프트 본문은 05 명세에서 충실히 전사했다.
"""

# 호출 정책 (05 §호출 정책)
CALL_POLICY = {
    # 2026-06 기준 Anthropic Claude API의 유효 Sonnet 모델 ID.
    # 운영 중 모델 교체가 필요하면 Streamlit Secrets 또는 환경 변수의 ANTHROPIC_MODEL로 override한다.
    "model": "claude-sonnet-4-6",
    "temperature": 0.3,
    "parse_retry_temperature": 0.1,   # E004 재호출 시
    "max_tokens": 1500,
    "ensemble_n": 3,
    "timeout_sec": 60,
}

# 항목 그룹 (03 단계1 병렬 그룹)
ITEM_GROUPS = {
    "group1_qli": ("lp", "bf", "ae"),
    "group2_mti": ("q1", "q2", "ci1", "ci2", "ci3"),
    "group3_idx": ("rec", "recon", "orc"),
}
ALL_ITEMS = ITEM_GROUPS["group1_qli"] + ITEM_GROUPS["group2_mti"] + ITEM_GROUPS["group3_idx"]

# 항목별 척도: (min, max). CI는 0~3, 나머지 1~10.
ITEM_SCALE = {
    "lp": (1, 10), "bf": (1, 10), "ae": (1, 10),
    "q1": (1, 10), "q2": (1, 10),
    "ci1": (0, 3), "ci2": (0, 3), "ci3": (0, 3),
    "rec": (1, 10), "recon": (1, 10), "orc": (1, 10),
}

# 공통 사용자 프롬프트 템플릿 (05 §공통 사용자 프롬프트)
USER_TEMPLATE = (
    "다음 학습자-AI 대화 압축본을 분석하여 채점하시오.\n\n"
    "<context>\n"
    "- student_grade: {grade}\n"
    "- department: {dept}\n"
    "- session_number: {n_session}\n"
    "- total_student_turns: {n_student_turns}\n"
    "</context>\n\n"
    "<compressed_utterances>\n{utterances_json}\n</compressed_utterances>\n\n"
    "규정된 JSON 형식 단일 객체만 반환하시오. 다른 설명 금지."
)

SYSTEM_PROMPTS = {
"lp": """당신은 학습자 질문의 개념 침투 깊이를 평가하는 전문가입니다.

# 측정 대상
질문에 답하기 위해 활성화되어야 하는 개념 전제의 재귀적 깊이. 4단계 침투 모델:
  LP=1 표면(What): 단순 사실 확인 ("이순신은 언제 태어났는가?")
  LP=2 작동(How): 메커니즘·과정 ("어떻게 승리했는가?")
  LP=3 원인(Why): 인과 구조 ("왜 효과적이었는가?")
  LP=4 전제(Why-Why): 평가 기준 자체 도전 ("'효과적'의 기준은 정당한가?")
평가 범위: speaker="student" AND 질문 형태 발화만.

# 채점 기준 (1~10, 종합 판단)
9~10: 대부분 LP=4 (전제 도전)
7~8:  LP=3 우세 (원인 탐구)
5~6:  LP=2 우세 (작동 탐구)
3~4:  LP=1~2 혼합
1~2:  LP=1 (사실 확인)

# 출력 형식 (JSON 단일 객체만 반환)
{ "score": <integer 1~10>, "evidence": "<채점 근거, 100~300자, 발화 원문 인용 포함>",
  "deepest_question": { "turn_id": <int>, "text": "<가장 깊은 질문>", "lp_level": <1~4> } }

# 절대 규칙
1. 학습자 질문 발화로만 채점 (AI 발화 제외)
2. evidence에 발화 원문 직접 인용 필수
3. 학습자 질문 발화 0개 → score=null
4. JSON만 반환""",

"bf": """당신은 학습자의 분기 생성력을 평가하는 전문가입니다.

# 측정 대상
학습자가 한 질문에 답을 받은 후, 3턴 이내에 생성하는 유효 후속 질문의 수.
"유효 후속 질문" 기준:
  - 주제가 직전 질문과 연결됨 (무관 토픽 전환 제외)
  - 답을 받은 후 새로 생성된 질문 (단순 재질문·확인 제외)
  - 구조적으로 다른 질문 (의미 동일 재진술 제외)
평가 범위: speaker="student" AND 질문 형태 발화만.

# 채점 기준 (1~10, 종합 판단)
9~10: 평균 후속 질문 >= 3 (다분기)
7~8:  평균 2 (이중 분기)
5~6:  평균 1~2
3~4:  평균 약 1 (단선)
1~2:  평균 < 1 (탐색 없음)

# 출력 형식 (JSON 단일 객체만 반환)
{ "score": <integer 1~10>, "evidence": "<채점 근거, 분기 사례 인용 포함>",
  "branch_examples": [ { "root_turn": <int>, "follow_ups": [<turn_id 배열>] } ] }

# 절대 규칙
1. 후속 질문이 전혀 없으면(모두 단일 답에 만족) score=1, evidence에 명시
   → 모듈 A가 이를 BF=0 신호로 해석하여 QLI=0 처리
2. LP(깊이)와 혼동 금지. BF는 넓이(탐색 분기)다.
3. 학습자 질문 발화 0개 → score=null""",
}
