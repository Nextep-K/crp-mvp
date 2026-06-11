import ast
from pathlib import Path

import compute_module as A
from crp_types import ClassCount, INSTITUTION_DEFAULTS, Judgment, round_half_up


def test_compute_module_has_no_llm_or_network_imports():
    source = Path("engines/phase_b_engine/compute_module.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"anthropic", "openai", "requests", "httpx", "streamlit"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in banned
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in banned


def test_normalize_qli_three_branches():
    assert A.normalize_qli(7, 6, 5, 0) is None
    assert A.normalize_qli(7, 0, 5, 5) == 0
    assert A.normalize_qli(8, 8, 8, 5) == 8


def test_weights_are_canonical():
    params = dict(INSTITUTION_DEFAULTS)
    assert params["weights_class"] == {"W_S": 4, "W_A": 3, "W_B": 2, "W_C": 1}
    assert params["mti_layer_weights"] == {"L1": 0.60, "L2": 0.25, "L3": 0.15}
    cc = ClassCount(s_weighted=1, has_any_class=True, transition_speed_turns=1)
    l1 = A.compute_mti_l1(cc, 5, params)
    assert l1.value is not None
    assert A.compute_mti_final(10, 6, 4, params["mti_layer_weights"]) == 8.1


def test_round_half_up_and_l3():
    assert round_half_up(2.5) == 3
    assert A.normalize_l3(0) == 1
    assert A.normalize_l3(9) == 10


def test_ensemble_and_output_versions():
    runs = [Judgment(lp=7, bf=7, ae=7, q1=7, q2=7, ci1=1, ci2=1, ci3=1, rec=7, recon=7, orc=7) for _ in range(3)]
    agg = A.aggregate_ensemble(runs)
    assert agg.mean["lp"] == 7
    out = A.assemble_crp_output(
        session_id="s1", student_id="u1",
        metrics={"MTI": 7, "QLI": 7, "Rec": 7, "Recon": 7, "Orc": 7},
        reliability={"low_reliability": False, "disengagement_flag": False},
        params_applied={"institution": "BNU"},
    )
    assert out["rubric_version"] == "v_f1"
    assert out["prompt_version"] == "p_f1.0"
    assert out["classifier_version"] == "cls-v1.0"
    assert out["hash"].startswith("sha256:")
