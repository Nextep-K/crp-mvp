"""
compute_module.py — CRP 엔진 모듈 A (연산 모듈)

★ 규칙 3: 이 모듈은 LLM을 절대 호출하지 않는다. 순수 결정론적 함수.
   동일 입력 → 동일 출력 (특허 재현성 청구 대상, 09 §4 측정 재현성).

캐노니컬: 02_루브릭_v_f1. 연산 순서: 03 §데이터흐름 A-1~A-11.

합의된 4개 공백 결정(코드에 강제):
  (1) 전환속도_턴수 = 첫 Class 발화까지의 학생 턴 수 (1-indexed)
  (2) 반올림 = round_half_up (2.5→3)
  (3) JUMP 대상 = MTI 단일
  (4) divergence_cause 우선순위 = pattern_pool_gap → llm_bias → implicit_metacog

명세 공백에 대한 보수적 처리(임의 동작 추가 아님, 정의 불가 시 None):
  - MTI_final: L1/L2/L3 중 하나라도 None이면 None (정의된 수식을 null 피연산자로 계산 불가)
  - A-3 '선언만 0.5 가중': B1 분류기 내부 영역(00 §7) — 라벨 액면 처리(A-3 = W_A×1)
"""
from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from typing import Optional, Sequence

from crp_types import (
    CLASS_SUBLEVEL, INSTITUTION_DEFAULTS, PIVOT_PAIRS,
    CLASSIFIER_VERSION, PROMPT_VERSION, RUBRIC_VERSION, SCHEMA_VERSION,
    ClassCount, DivergenceResult, EnsembleAgg, GrokkingResult, Judgment, L1Result,
    round_half_up, sigmoid,
)

# ════════════════════════════════════════════════════════════════════════
# 정규화 함수 (02 §3.1, §4.1) — round_half_up 적용
# ════════════════════════════════════════════════════════════════════════

def normalize_l1(raw: float, student_turn_count: int,
                 k: float = 0.6, midpoint: float = 1.5) -> int:
    density = raw / max(student_turn_count, 1)
    normalized = 1 + 9 * sigmoid(k * (density - midpoint))
    return round_half_up(normalized)


def normalize_l3(raw: float) -> int:
    # raw = CI1+CI2+CI3 (각 0~3, 합 0~9) → 1~10 선형
    normalized = 1 + 9 * (raw / 9)
    return round_half_up(normalized)


def normalize_qli(lp: float, bf: float, ae: float,
                  student_question_count: int) -> Optional[int]:
    """02 §4.1 3분기. q==0→None(+low_data_flag) / bf==0→0 / else 기하평균."""
    if student_question_count == 0:
        return None
    if bf == 0:
        return 0
    geomean = (lp * bf * ae) ** (1 / 3)
    if student_question_count < 3:
        confidence = student_question_count / 3
        geomean = geomean * confidence + 1 * (1 - confidence)
    return round_half_up(geomean)


# ════════════════════════════════════════════════════════════════════════
# A-(앙상블 집계) — 03 단계2. 33개 결과 → 11항목 mean/std. None은 평균에서 제외.
# ════════════════════════════════════════════════════════════════════════

def aggregate_ensemble(runs: Sequence[Judgment],
                       std_threshold: float = 1.5) -> EnsembleAgg:
    mean: dict = {}
    std: dict = {}
    for item in Judgment.ITEMS:
        vals = [getattr(r, item) for r in runs if getattr(r, item) is not None]
        if not vals:
            mean[item] = None
            std[item] = None
            continue
        mean[item] = sum(vals) / len(vals)
        std[item] = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    valid_std = [s for s in std.values() if s is not None]
    std_dev_max = max(valid_std) if valid_std else 0.0
    return EnsembleAgg(mean=mean, std=std,
                       std_dev_max=std_dev_max,
                       low_reliability=std_dev_max > std_threshold)


# ════════════════════════════════════════════════════════════════════════
# A-1: MTI_L1 — Class S/A/B/C 집계 + 공식 (02 §3, 03 A-1)
# ════════════════════════════════════════════════════════════════════════

def count_classes(utterances: Sequence[dict]) -> ClassCount:
    """
    압축본 발화 목록에서 Class 빈도 집계.
    하위가중 합산 카운트: 예) S = 3·n(S-1) + 2·n(S-2) + 1·n(S-3).
    전환속도_턴수 = 첫 비-N Class 발화까지의 학생 턴 수(1-indexed).
    """
    cc = ClassCount()
    student_turn_idx = 0
    for u in utterances:
        if u.get("speaker") != "student":
            continue
        student_turn_idx += 1
        label = u.get("class_label", "N") or "N"
        cls, mult = CLASS_SUBLEVEL.get(label, (None, 0))
        if cls is None:
            continue
        cc.has_any_class = True
        if cc.transition_speed_turns is None:
            cc.transition_speed_turns = student_turn_idx
        if cls == "S":
            cc.s_weighted += mult
            cc.class_s_count += 1
        elif cls == "A":
            cc.a_weighted += mult
        elif cls == "B":
            cc.b_weighted += mult
        elif cls == "C":
            cc.c_weighted += mult
    return cc


def compute_mti_l1(cc: ClassCount, student_turn_count: int,
                   params: dict) -> L1Result:
    low_data_min = params["low_data_min_turns"]
    # 02 §3.6 fallback
    if student_turn_count < low_data_min:
        return L1Result(value=None, low_data=True)
    if not cc.has_any_class:
        return L1Result(value=1.0, low_classification=True)

    w = params["weights_class"]
    raw_class = (cc.s_weighted * w["W_S"] + cc.a_weighted * w["W_A"]
                 + cc.b_weighted * w["W_B"] + cc.c_weighted * w["W_C"])
    # 전환속도 보정: 첫 전환이 빠를수록(턴수 작을수록) 계수↑
    t = cc.transition_speed_turns
    factor = (1 + 1 / t) if t else 1.0
    raw = raw_class * factor
    value = normalize_l1(raw, student_turn_count,
                         params["l1_sigmoid_k"], params["l1_sigmoid_midpoint"])
    return L1Result(value=float(value))


# ════════════════════════════════════════════════════════════════════════
# A-2/A-3/A-4: MTI L2, L3, final (02 §3.3-3.5, 03 A-2~A-4)
# ════════════════════════════════════════════════════════════════════════

def compute_mti_l2(q1_mean: Optional[float], q2_mean: Optional[float]) -> Optional[float]:
    # 02 §3.6: 자기 인식 발화 0건 → Q1,Q2=null → L2=null
    if q1_mean is None or q2_mean is None:
        return None
    return (q1_mean + q2_mean) / 2


def compute_mti_l3(ci1: Optional[float], ci2: Optional[float],
                   ci3: Optional[float]) -> Optional[float]:
    if ci1 is None or ci2 is None or ci3 is None:
        return None
    return float(normalize_l3(ci1 + ci2 + ci3))


def compute_mti_final(l1: Optional[float], l2: Optional[float],
                      l3: Optional[float], layer_weights: dict) -> Optional[float]:
    # 보수적: 정의된 가중합을 null 피연산자로 계산 불가 → None
    if l1 is None or l2 is None or l3 is None:
        return None
    return (l1 * layer_weights["L1"] + l2 * layer_weights["L2"]
            + l3 * layer_weights["L3"])


# ════════════════════════════════════════════════════════════════════════
# A-5: QLI (위 normalize_qli 사용, 03 A-5 3분기)
# ════════════════════════════════════════════════════════════════════════

def compute_qli(lp_mean: Optional[float], bf_mean: Optional[float],
                ae_mean: Optional[float], student_question_count: int):
    """반환: (qli, low_data_flag). q==0 → (None, True)."""
    if student_question_count == 0:
        return None, True
    if lp_mean is None or bf_mean is None or ae_mean is None:
        # 질문은 있으나 LP/BF/AE 채점 불가 → 데이터 부족
        return None, True
    # BF 프롬프트는 후속질문 0개를 score=1로 반환 → 모듈 A가 BF=0으로 해석(05 #2 절대규칙1).
    # 앙상블 평균을 반올림한 합의 점수가 1이면 비탐색(BF=0) 신호 → QLI=0, 플래그 없음.
    if round_half_up(bf_mean) == 1:
        return 0, False
    qli = normalize_qli(lp_mean, bf_mean, ae_mean, student_question_count)
    return qli, False


# ════════════════════════════════════════════════════════════════════════
# A-6: Divergence (02 §8, 06 §2.2) — 우선순위 A
# ════════════════════════════════════════════════════════════════════════

def check_divergence(l1: Optional[float], l2: Optional[float], l3: Optional[float],
                     threshold: float = 2.0) -> DivergenceResult:
    if l1 is None or l2 is None or l3 is None:
        return DivergenceResult(divergence=None, layer_inconsistency=False, cause=None)
    divergence = max(l1, l2, l3) - min(l1, l2, l3)
    if divergence <= threshold:
        return DivergenceResult(divergence=divergence, layer_inconsistency=False, cause=None)
    # 우선순위 A: pattern_pool_gap → llm_bias → implicit_metacog (첫 매치 채택)
    if l1 < 4 and l2 >= 6:
        cause = "pattern_pool_gap"
    elif l2 >= 7 and (l1 < 5 or l3 < 5):
        cause = "llm_bias"
    elif l3 >= 7 and l1 < 5:
        cause = "implicit_metacog"
    else:
        cause = None
    return DivergenceResult(divergence=divergence, layer_inconsistency=True, cause=cause)


# ════════════════════════════════════════════════════════════════════════
# A-7/A-8: Velocity, Acceleration (02 §7, 03 A-7/A-8) — 시간 정규화 없음
# ════════════════════════════════════════════════════════════════════════

def compute_velocity(series: Sequence[float]) -> Optional[float]:
    if len(series) < 2:
        return None
    return series[-1] - series[-2]


def compute_acceleration(series: Sequence[float]) -> Optional[float]:
    if len(series) < 3:
        return None
    return (series[-1] - series[-2]) - (series[-2] - series[-3])


# ════════════════════════════════════════════════════════════════════════
# A-9: Grokking (02 §7) — JUMP=MTI 단일, PIVOT=§7.4 쌍 규칙
# ════════════════════════════════════════════════════════════════════════

def _tau(metric: str, n_session: int, params: dict,
         personal_std: Optional[float]) -> Optional[float]:
    """τ = baseline_std × k. 콜드스타트 02 §7.3."""
    k = params.get("tau_k", params["tau_k_default"])
    if n_session <= 1:
        return None                                  # 탐지 불가
    if n_session in (2, 3):
        seed = params.get("tau_baseline_seed", {})
        std = seed.get(metric)
        return None if std is None else std * k
    # n>=4: 개인 baseline_std
    return None if personal_std is None else personal_std * k


def detect_grokking(metrics_history: Sequence[dict], params: dict,
                    personal_std: Optional[dict] = None,
                    qli_rec_inverse_streak: int = 0) -> GrokkingResult:
    """
    metrics_history: 세션별 {MTI,QLI,Rec,Recon,Orc} dict 리스트(시간순, 현재 세션 포함).
    personal_std: n>=4일 때 지표별 개인 baseline_std.
    qli_rec_inverse_streak: 직전까지 QLI↔Rec 역교차 연속 횟수(△ 3회연속 판정용).
    """
    n = len(metrics_history)
    if n < 2:
        return GrokkingResult()
    cur, prev = metrics_history[-1], metrics_history[-2]
    personal_std = personal_std or {}

    # JUMP — MTI 단일
    if cur.get("MTI") is not None and prev.get("MTI") is not None:
        tau_mti = _tau("MTI", n, params, personal_std.get("MTI"))
        if tau_mti is not None and (cur["MTI"] - prev["MTI"]) >= tau_mti:
            return GrokkingResult(detected=True, type="JUMP", metric="MTI")

    # PIVOT — Inverse Crossover. 각 |Δ| ≥ τ/2, 방향 반대.
    def delta(m):
        a, b = cur.get(m), prev.get(m)
        return None if a is None or b is None else a - b

    orc_recon_alert = False
    for pair, rule in PIVOT_PAIRS.items():
        if rule is False:
            continue
        m1, m2 = tuple(pair)
        d1, d2 = delta(m1), delta(m2)
        if d1 is None or d2 is None:
            continue
        if (d1 > 0) == (d2 > 0) or d1 == 0 or d2 == 0:
            continue  # 같은 방향 또는 무변화 → PIVOT 아님
        t1 = _tau(m1, n, params, personal_std.get(m1))
        t2 = _tau(m2, n, params, personal_std.get(m2))
        if t1 is None or t2 is None:
            continue
        if abs(d1) < t1 / 2 or abs(d2) < t2 / 2:
            continue
        if rule == "alert":                # Orc↔Recon: 알림만, PIVOT 아님
            orc_recon_alert = True
            continue
        if rule == "consecutive3":         # QLI↔Rec: 3회 연속 시에만 인정
            if qli_rec_inverse_streak + 1 < 3:
                continue
        return GrokkingResult(detected=True, type="PIVOT", pair=(m1, m2),
                              orc_recon_alert=orc_recon_alert)
    return GrokkingResult(detected=False, orc_recon_alert=orc_recon_alert)


# ════════════════════════════════════════════════════════════════════════
# 측정 회피 1차 — 모듈 A 규칙 기반 4조건 (02 §3.6, 06 §9). LLM 없음.
# ════════════════════════════════════════════════════════════════════════

def detect_disengagement_rulebased(metadata: dict, params: dict,
                                   avg_session_min: Optional[float] = None) -> tuple[bool, int]:
    """반환: (1차 플래그, 충족 조건 수). avg_session_min 미제공 시 조건④ 평가 제외."""
    min_cond = params["disengagement_min_conditions"]
    conditions = [
        metadata.get("avg_utterance_length", 999) < 10,       # ①
        metadata.get("question_ratio", 1.0) < 0.05,           # ②
        metadata.get("repeat_ratio", 0.0) > 0.50,             # ③
    ]
    if avg_session_min:                                        # ④ (모집단 평균 필요)
        conditions.append(metadata.get("session_duration_min", 999) < 0.30 * avg_session_min)
    met = sum(1 for c in conditions if c)
    return met >= min_cond, met


# ════════════════════════════════════════════════════════════════════════
# A-10: 파라미터 계층 — 기관→전공→교수 키 단위 머지 (03 A-10, 04 §3)
# ════════════════════════════════════════════════════════════════════════

def resolve_params(config: dict, dept_id: Optional[str] = None,
                   prof_id: Optional[str] = None) -> dict:
    inst = config.get("institution", {})
    resolved = dict(INSTITUTION_DEFAULTS)
    resolved.update(inst.get("defaults", {}))
    resolved["institution_id"] = inst.get("id")

    if dept_id:
        for d in config.get("departments", []):
            if d.get("id") == dept_id:
                for key, val in d.get("overrides", {}).items():
                    resolved[key] = val            # 키 단위 교체
                if "tau_baseline_seed" in d:
                    resolved["tau_baseline_seed"] = d["tau_baseline_seed"]
                resolved["dept_id"] = dept_id
                break
    if prof_id:
        for p in config.get("professors", []):
            if p.get("id") == prof_id:
                if "smart_weights" in p:
                    resolved["smart_weights"] = p["smart_weights"]
                if "tau_k_override" in p:
                    resolved["tau_k"] = p["tau_k_override"]
                resolved["prof_id"] = prof_id
                break
    return resolved


# ════════════════════════════════════════════════════════════════════════
# A-11: CRP_output 조립 + SHA-256 (03 A-11, 04 §2). 버전 3종 기록(규칙 6).
# ════════════════════════════════════════════════════════════════════════

def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_of(obj: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def assemble_crp_output(*, session_id: str, student_id: str, metrics: dict,
                        reliability: dict, params_applied: dict,
                        velocity: Optional[dict] = None,
                        acceleration: Optional[dict] = None,
                        grokking: Optional[dict] = None,
                        entry_profile: Optional[dict] = None,
                        interpretation_text: Optional[dict] = None,
                        qualitative_band: Optional[dict] = None,
                        percentile: Optional[dict] = None,
                        classifier_version: str = CLASSIFIER_VERSION) -> dict:
    out = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "student_id": student_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metrics": metrics,
        "interpretation_text": interpretation_text or {},
        "qualitative_band": qualitative_band or {},
        "velocity": velocity or {},
        "acceleration": acceleration or {},
        "grokking": grokking or {"detected": False, "type": None},
        "reliability": reliability,
        "params_applied": params_applied,
        "rubric_version": RUBRIC_VERSION,      # 규칙 6
        "prompt_version": PROMPT_VERSION,      # 규칙 6
        "classifier_version": classifier_version,
    }
    # 선택 필드 — Phase A는 metrics와 합산 금지, 병렬 보관만 (규칙 5, 07 §4)
    if entry_profile is not None:
        out["entry_profile"] = entry_profile
    if percentile is not None:
        out["percentile"] = percentile
    out["hash"] = sha256_of(out)
    return out
