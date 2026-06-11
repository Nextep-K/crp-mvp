"""
phase_b_engine — CRP Phase B 오케스트레이터

compressed → judgment_module(모듈 B) → compute_module(모듈 A A-1~A-11) → CRP_output
"""
from __future__ import annotations

from typing import Optional

import compute_module as A
from aux_prompts import detect_disengagement_llm
from judgment_module import LLMClient, run_judgment


def _metric_series(metrics_history: list[dict], key: str, current):
    vals = [m.get(key) for m in metrics_history if m.get(key) is not None]
    if current is not None:
        vals.append(current)
    return vals


def measure_session(compressed: dict, client: LLMClient, params: dict,
                    *, metrics_history: Optional[list[dict]] = None,
                    avg_session_min: Optional[float] = None,
                    sleep_fn=None) -> dict:
    """단일 Phase B 세션 측정. 실제 LLM 클라이언트 또는 Mock 클라이언트를 주입한다."""
    if sleep_fn is None:
        import time
        sleep_fn = time.sleep
    metrics_history = metrics_history or []
    md = compressed.get("metadata", {})
    utterances = compressed.get("compressed_utterances", [])

    # 모듈 B: 11항목 × N회
    runs = run_judgment(client, compressed, ensemble_n=params.get("ensemble_n", 3), sleep_fn=sleep_fn)

    # 모듈 A: A-1~A-11 순차 연산
    agg = A.aggregate_ensemble(runs, params.get("ensemble_std_threshold", 1.5))
    cc = A.count_classes(utterances)
    l1 = A.compute_mti_l1(cc, md.get("student_turn_count", 0), params)
    l2 = A.compute_mti_l2(agg.mean.get("q1"), agg.mean.get("q2"))
    l3 = A.compute_mti_l3(agg.mean.get("ci1"), agg.mean.get("ci2"), agg.mean.get("ci3"))
    mti = A.compute_mti_final(l1.value, l2, l3, params["mti_layer_weights"])
    qli, q_low = A.compute_qli(agg.mean.get("lp"), agg.mean.get("bf"), agg.mean.get("ae"), md.get("student_question_count", 0))
    div = A.check_divergence(l1.value, l2, l3, params.get("divergence_threshold", 2.0))
    d1_flag, d1_count = A.detect_disengagement_rulebased(md, params, avg_session_min)
    d2 = None
    disengage_flag = d1_flag
    if d1_flag:
        d2 = detect_disengagement_llm(client, utterances, sleep_fn=sleep_fn)
        disengage_flag = d2.flag

    metrics = {
        "MTI": mti,
        "MTI_L1": l1.value,
        "MTI_L2": l2,
        "MTI_L3": l3,
        "MTI_L1_classS_count": cc.class_s_count,
        "QLI": qli,
        "Rec": agg.mean.get("rec"),
        "Recon": agg.mean.get("recon"),
        "Orc": agg.mean.get("orc"),
        "session_duration_min": md.get("session_duration_min"),
    }
    velocity = {k: A.compute_velocity(_metric_series(metrics_history, k, metrics.get(k))) for k in ["MTI", "QLI", "Rec", "Recon", "Orc"]}
    acceleration = {k: A.compute_acceleration(_metric_series(metrics_history, k, metrics.get(k))) for k in ["MTI", "QLI", "Rec", "Recon", "Orc"]}
    grok = A.detect_grokking(metrics_history + [metrics], params)

    reliability = {
        "std_dev_max": agg.std_dev_max,
        "low_reliability": agg.low_reliability,
        "low_data_flag": bool(l1.low_data or q_low),
        "layer_inconsistency": div.layer_inconsistency,
        "divergence": div.divergence,
        "divergence_cause": div.cause,
        "disengagement_flag": bool(disengage_flag),
        "disengagement_rule_count": d1_count,
        "disengagement_severity": getattr(d2, "severity", "none") if d2 else "none",
    }

    return A.assemble_crp_output(
        session_id=compressed.get("session_id", ""),
        student_id=compressed.get("student_id", ""),
        metrics=metrics,
        reliability=reliability,
        params_applied={
            "institution": params.get("institution_id"),
            "department": params.get("dept_id"),
            "professor": params.get("prof_id"),
        },
        velocity=velocity,
        acceleration=acceleration,
        grokking=grok.__dict__,
        qualitative_band={"MTI": {"band": "MVP_pending"}},
        classifier_version=md.get("classifier_version", A.CLASSIFIER_VERSION),
    )
