from datetime import timedelta

import pytest

from app.service import GateError, StateError
from run_eval import EDGE, P47, T0, finish_tasks, fresh, governance_cases, naive, run_to_dispatch, verification_cases
from app.synthetic import photo


def test_report_fuses_risk_locates_asset_and_sets_sla():
    fp, _ = fresh()
    e = fp.report(description=EDGE, reporter="班组长 李明", reported_risk="LOW")
    assert e["final_risk"] == "HIGH" and e["reported_risk"] == "LOW"  # never lowered below the signals
    assert e["asset_id"] == "P47" and e["asset_method"] == "text" and e["stop_work"]
    assert e["close_due"] > e["response_due"]
    assert e["findings"][0]["status"] == "SUPPORTED" and e["findings"][0]["evidence_refs"]


def test_gps_and_qr_location():
    fp, _ = fresh()
    assert fp.report(description="临边防护缺失", reporter="x", lat=P47[0] + 0.0003, lon=P47[1])["asset_method"] == "gps"
    assert fp.report(description="临边防护缺失", reporter="x", qr="asset:S12")["asset_id"] == "S12"
    with pytest.raises(ValueError):
        fp.report(description="临边防护缺失", reporter="x", asset_id="NOPE")


def test_reporter_can_raise_risk():
    fp, _ = fresh()
    assert fp.report(description="Housekeeping debris near P52", reporter="x", reported_risk="HIGH")["final_risk"] == "HIGH"


def test_full_closed_loop():
    fp, clock = fresh()
    ev, _ = run_to_dispatch(fp, clock, photo("before", captured_at=naive(T0), lat=P47[0], lon=P47[1]))
    clock.t += timedelta(hours=2)
    finish_tasks(fp, ev["id"])
    after = fp.store_media(photo("after", captured_at=naive(clock.t), lat=P47[0], lon=P47[1]))
    v = fp.reinspect(ev["id"], inspector="安全员 周工", observation="复检合格", resolved=True, photos=[after["sha256"]])
    assert v["status"] == "VERIFIED"
    closed = fp.close(ev["id"], "项目经理 张工")
    assert closed["status"] == "CLOSED" and {r["kind"] for r in closed["receipts"]} == {"approval", "dispatch", "verification"}
    d = fp.dashboard()
    assert d["closed_within_sla"] == 1.0 and d["verification_first_pass_rate"] == 1.0


def test_failed_reinspection_can_be_repeated():
    fp, clock = fresh()
    ev, before = run_to_dispatch(fp, clock, photo("before"))
    finish_tasks(fp, ev["id"])
    assert fp.reinspect(ev["id"], inspector="安全员 周工", observation="复用旧照", resolved=True, photos=[before["sha256"]])["status"] == "VERIFICATION_FAILED"
    clock.t += timedelta(hours=1)
    good = fp.store_media(photo("after", captured_at=naive(clock.t), lat=P47[0], lon=P47[1]))
    assert fp.reinspect(ev["id"], inspector="安全员 周工", observation="复检合格", resolved=True, photos=[good["sha256"]])["status"] == "VERIFIED"


class ResidualVisionModel:
    def complete_json(self, system, user, schema):
        return None

    def complete_vision(self, system, text, uri, schema):
        return {"hazards": [{"label": "unprotected_edge", "confidence": 0.91,
                             "visible_evidence": "guardrail opening remains visible"}]}


def test_failed_reinspection_explains_incomplete_tasks_and_visual_hazards():
    fp, clock = fresh()
    fp.model = ResidualVisionModel()
    ev, _ = run_to_dispatch(fp, clock, photo("before", captured_at=naive(T0), lat=P47[0], lon=P47[1]))
    clock.t += timedelta(hours=1)
    after = fp.store_media(photo("after", captured_at=naive(clock.t), lat=P47[0], lon=P47[1]))
    result = fp.reinspect(ev["id"], inspector="安全员 周工", observation="整改完成", resolved=True,
                          photos=[after["sha256"]])
    receipt = [r for r in result["receipts"] if r["kind"] == "verification"][-1]
    payload = receipt["payload"]
    assert result["status"] == "VERIFICATION_FAILED"
    assert payload["incomplete_tasks"][0]["status"] == "DISPATCHED"
    assert payload["vision_hazards"] == [{"photo_sha256": after["sha256"], "label": "unprotected_edge",
                                           "confidence": 0.91, "visible_evidence": "guardrail opening remains visible"}]
    assert {reason["code"] for reason in payload["failure_reasons"]} == {"all_tasks_done", "hazard_cleared"}


def test_task_needs_dispatch_and_a_human():
    fp, clock = fresh()
    ev = fp.report(description=EDGE, reporter="x")
    task = ev["tasks"][0]["id"]
    with pytest.raises(StateError):
        fp.complete_task(task, "整改班组 陈工", "done")
    fp.approve(ev["id"], "项目经理 张工")
    fp.dispatch(ev["id"], "现场经理 王工")
    with pytest.raises(GateError):
        fp.complete_task(task, "agent:crew", "done")


def test_unknown_signature_rejected():
    fp, _ = fresh()
    with pytest.raises(ValueError):
        fp.store_media(b"MZ\x90\x00 not an image")


@pytest.mark.parametrize("case", verification_cases(), ids=lambda c: c["case"])
def test_verification_scenarios(case):
    assert case["ok"], case


@pytest.mark.parametrize("case", governance_cases(), ids=lambda c: c["case"])
def test_governance(case):
    assert case["ok"], case
