"""
crp_types.py — CRP 엔진 공용 타입·상수·데이터 계약

단일 진실 원천(SoT): 02_루브릭_v_f1 (캐노니컬). 04_데이터스키마 / 03_구조설계 파생.
충돌 시 02 우선. 명세에 없는 동작은 추가하지 않는다.

버전 3종은 모든 측정 결과에 기록한다(규칙 6).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

# ── 버전 상수 (04 §2.1, 규칙 6) ────────────────────────────────────────────
SCHEMA_VERSION = "1.0_f1"
RUBRIC_VERSION = "v_f1"
PROMPT_VERSION = "p_f1.0"
CLASSIFIER_VERSION = "cls-v1.0"

# ── 기관 기본 파라미터 (04 §3 institution.defaults) ─────────────────────────
INSTITUTION_DEFAULTS = {
    "weights_class": {"W_S": 4, "W_A": 3, "W_B": 2, "W_C": 1},
    "mti_layer_weights": {"L1": 0.60, "L2": 0.25, "L3": 0.15},
    "ensemble_n": 3,
    "ensemble_std_threshold": 1.5,
    "divergence_threshold": 2.0,
    "low_data_min_turns": 5,
    "tau_k_default": 2.0,
    "session_timeout_min": 15,
    "session_max_min": 90,
    "l1_sigmoid_k": 0.6,
    "l1_sigmoid_midpoint": 1.5,        # 02 §3.1 normalize_l1 midpoint
    "disengagement_min_conditions": 2,
}

# Class 하위 라벨 → (대분류, 하위 가중치 배수) (02 §3.2, 04 §1.4)
#   S-1=W_S×3 ... C-3=W_C×1.  대분류 가중치 W_*는 파라미터에서 주입.
CLASS_SUBLEVEL = {
    "S-1": ("S", 3), "S-2": ("S", 2), "S-3": ("S", 1),
    "A-1": ("A", 3), "A-2": ("A", 2), "A-3": ("A", 1),
    "B-1": ("B", 3), "B-2": ("B", 2), "B-3": ("B", 1),
    "C-1": ("C", 3), "C-2": ("C", 2), "C-3": ("C", 1),
    "N": (None, 0),
}

# PIVOT 인정 쌍 (02 §7.4). True=무조건 인정(○), "consecutive3"=3회연속(△),
# "alert"=PIVOT아님·알림만(△), False=노이즈(✕).
PIVOT_PAIRS = {
    frozenset(("Recon", "Rec")): True,
    frozenset(("Orc", "MTI")): True,
    frozenset(("QLI", "Recon")): True,
    frozenset(("Rec", "MTI")): True,
    frozenset(("QLI", "MTI")): True,
    frozenset(("Orc", "Recon")): "alert",
    frozenset(("QLI", "Rec")): "consecutive3",
    frozenset(("Recon", "MTI")): False,
    frozenset(("Orc", "Rec")): False,
    frozenset(("QLI", "Orc")): False,
}


def round_half_up(x: float) -> int:
    """일반 반올림 강제 (2.5→3). Python 기본 round의 banker's rounding 회피."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ── 모듈 B → 모듈 A 전달 구조 (03 인터페이스) ────────────────────────────────
@dataclass
class Judgment:
    """앙상블 1회 결과. 점수는 정수 또는 null(측정 불가). 03 모듈 B 출력."""
    lp: Optional[int] = None
    bf: Optional[int] = None
    ae: Optional[int] = None
    q1: Optional[int] = None
    q2: Optional[int] = None
    ci1: Optional[int] = None
    ci2: Optional[int] = None
    ci3: Optional[int] = None
    rec: Optional[int] = None
    recon: Optional[int] = None
    orc: Optional[int] = None

    ITEMS = ("lp", "bf", "ae", "q1", "q2", "ci1", "ci2", "ci3", "rec", "recon", "orc")


@dataclass
class EnsembleAgg:
    """A-앙상블 집계 결과: 항목별 평균·표준편차. None은 평균 계산에서 제외."""
    mean: dict          # item -> float | None
    std: dict           # item -> float | None
    std_dev_max: float
    low_reliability: bool


@dataclass
class ClassCount:
    """L1 입력. 대분류별 '하위가중 합산 카운트' + 첫 전환 턴 수."""
    s_weighted: int = 0
    a_weighted: int = 0
    b_weighted: int = 0
    c_weighted: int = 0
    class_s_count: int = 0                    # MTI_L1_classS_count 추적용 (04 §2.2)
    has_any_class: bool = False
    transition_speed_turns: Optional[int] = None  # 첫 Class 발화까지의 학생 턴 수


@dataclass
class L1Result:
    value: Optional[float]
    low_data: bool = False
    low_classification: bool = False


@dataclass
class DivergenceResult:
    divergence: Optional[float]
    layer_inconsistency: bool
    cause: Optional[str]  # 'pattern_pool_gap'|'llm_bias'|'implicit_metacog'|None


@dataclass
class ClsSResult:
    """CLS-S 보조 프롬프트 결과 (05). class_confidence<0.6 경계 발화만 호출."""
    is_class_s: bool = False
    sub_label: Optional[str] = None         # 'S-1'|'S-2'|'S-3'|None
    confidence: float = 0.0
    fallback_label: Optional[str] = None    # S 아닐 경우 추천 라벨 A-1~C-3 또는 N
    reason: str = ""


@dataclass
class DisengageResult:
    """DISENGAGE 보조 프롬프트 결과 (05, 06 §9). 1차 플래그 세션만 2차 검증."""
    disengagement_detected: bool = False
    severity: str = "none"                  # none|mild|moderate|severe
    engaged_ratio: float = 1.0
    signals: list = field(default_factory=list)
    reason: str = ""

    @property
    def flag(self) -> bool:
        # severity moderate 이상일 때만 측정 제외 (06 §9)
        return self.severity in ("moderate", "severe")


@dataclass
class GrokkingResult:
    detected: bool = False
    type: Optional[str] = None              # 'JUMP' | 'PIVOT' | None
    metric: Optional[str] = None            # JUMP 대상 (MTI 단일)
    pair: Optional[tuple] = None            # PIVOT 쌍
    orc_recon_alert: bool = False           # Orc↔Recon 조건부 알림 (PIVOT 아님)
