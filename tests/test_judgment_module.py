import json

import aux_prompts as AUX
import judgment_module as B
import prompts as P

NULL = lambda *a: None


def _valid_payload(item):
    lo, _ = P.ITEM_SCALE[item]
    score = lo if lo == 0 else 7
    return json.dumps({"score": score, "evidence": f"근거 인용 포함 ({item})"}, ensure_ascii=False)


class GoodClient:
    def __init__(self):
        self.calls = 0
    def complete(self, system, user, **kw):
        self.calls += 1
        for item, sp in P.SYSTEM_PROMPTS.items():
            if sp == system:
                return _valid_payload(item)
        return json.dumps({"is_class_s": True, "sub_label": "S-1", "confidence": 0.85, "reason": "프레임 도전"}, ensure_ascii=False)


class ParseErrorOnce:
    def __init__(self):
        self.calls = 0
        self.retry_temp = None
    def complete(self, system, user, **kw):
        self.calls += 1
        if self.calls == 1:
            return "not json"
        self.retry_temp = kw.get("temperature")
        return json.dumps({"score": 7, "evidence": "근거"})


class TimeoutThenGood:
    def __init__(self): self.first = True
    def complete(self, system, user, **kw):
        if self.first:
            self.first = False
            raise TimeoutError()
        return json.dumps({"score": 7, "evidence": "근거"})


def test_run_judgment_33_calls():
    compressed = {"metadata": {"student_turn_count": 3}, "compressed_utterances": []}
    c = GoodClient()
    runs = B.run_judgment(c, compressed, ensemble_n=3, sleep_fn=NULL)
    assert len(runs) == 3
    assert c.calls == 33
    assert runs[0].lp == 7
    assert runs[0].ci1 == 0


def test_parse_retry_and_timeout_retry():
    pe = ParseErrorOnce()
    assert B.score_item(pe, "lp", "u", sleep_fn=NULL) == 7
    assert pe.retry_temp == 0.1
    assert B.score_item(TimeoutThenGood(), "lp", "u", sleep_fn=NULL) == 7


def test_evidence_missing_policy():
    class MissingEvidence:
        def complete(self, system, user, **kw):
            return json.dumps({"score": 7})
    assert B.score_item(MissingEvidence(), "lp", "u", sleep_fn=NULL) is None


def test_aux_cls_s_and_disengage():
    cls = AUX.classify_class_s(GoodClient(), "이 질문이 올바른가?", [], "C-2", sleep_fn=NULL)
    assert cls.is_class_s and cls.sub_label == "S-1"

    class DisengageClient:
        def complete(self, system, user, **kw):
            return json.dumps({"disengagement_detected": True, "severity": "moderate", "engaged_ratio": 0.2, "signals": [], "reason": "반복"})
    assert AUX.detect_disengagement_llm(DisengageClient(), [], sleep_fn=NULL).flag
