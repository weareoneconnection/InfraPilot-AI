#!/usr/bin/env python3
"""InfraPilot benchmark: field perception, closed-loop verification and governance.

Three suites, deterministic and offline (synthetic photos are generated):

* events       - 18 bilingual reports: risk, specialist routing, asset location, stop-work
                 (includes adversarial substrings such as "knowledge"/"ledge"/"edgeless")
* verification - 10 before/after re-inspection scenarios: valid, reused photo, re-encoded
                 photo, photo taken before dispatch, outside the geofence, no GPS with and
                 without attestation, inspector who did the work, open task, hazard not cleared
* governance   - dispatch without approval, non-human approver, close without verification,
                 analysis after approval, SLA overdue detection, precedent learning
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.service import FieldPilot, GateError, StateError  # noqa: E402
from app.store import Store  # noqa: E402
from app.synthetic import photo, reencode  # noqa: E402

T0 = datetime(2026, 10, 17, 8, 0, tzinfo=timezone.utc)
EDGE = "P47墩临边防护缺失，工人在高处作业未系安全带，下午还要继续施工。"


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


def fresh():
    clock = Clock()
    return FieldPilot(Store(tempfile.mktemp(suffix=".db")), clock=clock), clock


def naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def run_to_dispatch(fp, clock, before_bytes):
    before = fp.store_media(before_bytes)
    ev = fp.report(description=EDGE, reporter="班组长 李明", photos=[before["sha256"]])
    clock.t += timedelta(minutes=20)
    fp.approve(ev["id"], "项目经理 张工")
    fp.dispatch(ev["id"], "现场经理 王工")
    return ev, before


def finish_tasks(fp, ev_id, actor="整改班组 陈工"):
    for t in fp.event(ev_id)["tasks"]:
        fp.complete_task(t["id"], actor, "已安装防护栏杆并检查安全带挂点")


P47 = (3.139000, 101.686900)


def scenario(name, expect, *, after=None, inspector="安全员 周工", resolved=True, attest=False, skip_tasks=False):
    fp, clock = fresh()
    before = photo("before", captured_at=naive(T0 - timedelta(minutes=5)), lat=P47[0] + 0.0002, lon=P47[1] + 0.0002)
    ev, _ = run_to_dispatch(fp, clock, before)
    clock.t += timedelta(hours=5)
    if not skip_tasks:
        finish_tasks(fp, ev["id"])
    after_bytes = after(before) if after else photo("after", captured_at=naive(clock.t), lat=P47[0] + 0.0003, lon=P47[1] + 0.0001)
    sha = fp.store_media(after_bytes)["sha256"]
    out = fp.reinspect(ev["id"], inspector=inspector, observation="复检：防护栏杆已安装，安全带挂点有效", resolved=resolved,
                       photos=[sha], attest_location=attest)
    receipt = [r for r in out["receipts"] if r["kind"] == "verification"][-1]
    got = receipt["status"] == "PASSED"
    return {"case": name, "expect_pass": expect, "passed": got, "ok": got == expect,
            "failed_checks": [k for k, v in receipt["payload"]["checks"].items() if not v]}


def verification_cases():
    later = lambda: naive(T0 + timedelta(hours=5, minutes=30))  # noqa: E731
    return [
        scenario("valid_reinspection", True),
        scenario("same_photo_reused", False, after=lambda b: b),
        scenario("before_photo_reencoded", False, after=lambda b: reencode(b)),
        scenario("after_photo_taken_before_dispatch", False,
                 after=lambda b: photo("after", captured_at=naive(T0 + timedelta(minutes=5)), lat=P47[0], lon=P47[1])),
        scenario("after_photo_outside_geofence", False,
                 after=lambda b: photo("after", captured_at=later(), lat=P47[0] + 0.02, lon=P47[1] + 0.02)),
        scenario("no_gps_not_attested", False, after=lambda b: photo("after", captured_at=later())),
        scenario("no_gps_attested_by_inspector", True, after=lambda b: photo("after", captured_at=later()), attest=True),
        scenario("inspector_did_the_work", False, inspector="整改班组 陈工"),
        scenario("task_not_done", False, skip_tasks=True),
        scenario("hazard_not_cleared", False, resolved=False),
    ]


def governance_cases():
    out = []

    def case(name, fn):
        try:
            ok, detail = fn()
        except Exception as exc:  # unexpected errors fail the case
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        out.append({"case": name, "ok": bool(ok), "detail": detail})

    def dispatch_without_approval():
        fp, _ = fresh()
        ev = fp.report(description=EDGE, reporter="班组长 李明")
        try:
            fp.dispatch(ev["id"], "现场经理 王工")
            return False, "dispatched"
        except GateError as exc:
            return True, str(exc)

    def non_human_approver():
        fp, _ = fresh()
        ev = fp.report(description=EDGE, reporter="班组长 李明")
        blocked = 0
        for actor in ("agent:hse", "model:qwen-vl", "system", "auto-approve", ""):
            try:
                fp.approve(ev["id"], actor)
            except GateError:
                blocked += 1
        return blocked == 5, f"{blocked}/5 rejected"

    def close_without_verification():
        fp, clock = fresh()
        ev, _ = run_to_dispatch(fp, clock, photo("before"))
        try:
            fp.close(ev["id"], "项目经理 张工")
            return False, "closed"
        except GateError as exc:
            return True, str(exc)

    def analysis_frozen_after_approval():
        fp, clock = fresh()
        ev, _ = run_to_dispatch(fp, clock, photo("before"))
        try:
            fp.analyse(ev["id"])
            return False, "re-analysed after dispatch"
        except StateError as exc:
            return True, str(exc)

    def sla_overdue():
        fp, clock = fresh()
        ev = fp.report(description=EDGE, reporter="班组长 李明")
        clock.t += timedelta(hours=5)
        e = fp.event(ev["id"])
        clock.t += timedelta(hours=70)
        e2 = fp.event(ev["id"])
        return e["sla"]["response_overdue"] and not e["sla"]["close_overdue"] and e2["sla"]["close_overdue"], \
            f"HIGH: respond 4h, close 72h; at +5h response_overdue={e['sla']['response_overdue']}, at +75h close_overdue={e2['sla']['close_overdue']}"

    def precedent_learning():
        fp, clock = fresh()
        before = photo("before", captured_at=naive(T0), lat=P47[0], lon=P47[1])
        ev, _ = run_to_dispatch(fp, clock, before)
        clock.t += timedelta(hours=3)
        finish_tasks(fp, ev["id"])
        after = fp.store_media(photo("after", captured_at=naive(clock.t), lat=P47[0], lon=P47[1]))
        fp.reinspect(ev["id"], inspector="安全员 周工", observation="复检合格", resolved=True, photos=[after["sha256"]])
        fp.close(ev["id"], "项目经理 张工")
        nxt = fp.report(description="P47墩东侧临边又发现防护栏杆缺失", reporter="班组长 李明")
        return any(p["id"] == ev["id"] for p in nxt["precedents"]), f"precedents: {[p['id'] for p in nxt['precedents']]}"

    for name, fn in [("dispatch_without_approval_blocked", dispatch_without_approval), ("non_human_approval_rejected", non_human_approver),
                     ("close_without_verification_blocked", close_without_verification), ("analysis_frozen_after_approval", analysis_frozen_after_approval),
                     ("sla_overdue_detected", sla_overdue), ("closed_event_becomes_precedent", precedent_learning)]:
        case(name, fn)
    return out


def event_cases():
    fp, _ = fresh()
    out = []
    for line in (BASE / "data" / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        e = fp.report(description=row["text"], reporter="tester")
        team = [f["agent_id"] for f in e["findings"]]
        checks = {"risk": e["final_risk"] == row["risk"], "routing": team[: len(row["team"])] == row["team"],
                  "asset": e["asset_id"] == row["asset"], "stop_work": e["stop_work"] == row["stop"],
                  "grounded": all(f["evidence_refs"] for f in e["findings"] if f["status"] == "SUPPORTED")}
        out.append({"id": row["id"], "ok": all(checks.values()), "checks": checks, "risk": e["final_risk"], "team": team})
    return out


def main() -> int:
    events, verification, governance = event_cases(), verification_cases(), governance_cases()
    rate = lambda xs, key=None: round(100 * sum((x["checks"][key] if key else x["ok"]) for x in xs) / len(xs), 1)  # noqa: E731
    metrics = {
        "risk_accuracy": rate(events, "risk"), "routing_accuracy": rate(events, "routing"), "asset_location_accuracy": rate(events, "asset"),
        "stop_work_accuracy": rate(events, "stop_work"), "verification_accuracy": rate(verification),
        "governance_checks_passed": rate(governance),
    }
    gates = {k: 100.0 for k in metrics}
    passed = all(metrics[k] >= v for k, v in gates.items())
    print(json.dumps({"suite": "INFRAPILOT_BENCHMARK", "version": "2.0", "status": "PASSED" if passed else "FAILED",
                      "cases": len(events) + len(verification) + len(governance), "metrics": metrics, "gates": gates,
                      "events": [e for e in events if not e["ok"]], "verification": verification, "governance": governance},
                     ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
