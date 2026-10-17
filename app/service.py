"""Field event lifecycle: sense → assess → plan → human gate → dispatch → rectify → re-inspect → verify → close → learn.

* **Sense.** Text, photos (signature-checked, SHA-256, perceptual hash, EXIF
  time and GPS), an asset id, a QR payload or GPS position locate the event on
  a registered asset.
* **Assess.** Risk is the highest of the reporter, the text signals and the
  (optional, taxonomy-validated) vision model -- never lowered. The risk sets
  the response and closure SLAs and whether work must stop.
* **Plan.** Specialists are routed by the governed evidence the event
  retrieves; each finding cites real sources or reports a gap.
* **Human gate.** Only a named human approves; dispatch creates owned tasks
  due within the SLA.
* **Verify.** Closure needs an independent re-inspection whose after-photo
  is new (different hash and perceptual hash from every before-photo), taken
  after dispatch, at the asset (within its geofence, or attested), by someone
  who did not do the work, with every task done.
* **Learn.** Closed events become precedents for the same asset or hazard.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .knowledge import KnowledgeIndex, load_packs
from .llm import Model
from .perception import HAZARD_TAXONOMY, dhash, distance_m, exif_facts, hamming, sniff, vision_hazards
from .risk import SLA_HOURS, assess, higher, stop_work
from .store import Store

PACKS = Path(__file__).resolve().parent / "packs"
ASSETS = Path(__file__).resolve().parent.parent / "data" / "assets.json"
REUSE_DISTANCE = 10  # of 512 dHash bits: at or below this the "after" photo is the same picture re-saved
HUMAN_FORBIDDEN = ("agent:", "model:", "system", "policy:", "auto")
MAX_MEDIA = 25 * 1024 * 1024

SPECIALISTS = {
    "hse": {"name": "HSE 智能体", "domain": "hse", "owner": "HSE Manager / HSE 经理",
            "action": "Stop the unsafe activity, isolate the area and install the required controls before restart / 停止不安全作业、隔离并落实管控后复工"},
    "quality": {"name": "质量智能体", "domain": "quality", "also": ["asset"], "owner": "QA/QC Manager / 质量经理",
                "action": "Raise an NCR, record location and dimensions, and obtain engineering disposition / 开具不符合项、记录位置尺寸并取得工程处置意见"},
    "plant": {"name": "设备吊装智能体", "domain": "plant", "owner": "Plant Manager / 设备经理",
              "action": "Hold the lift until the lift plan and equipment certificates are verified / 吊装方案和设备证书核实前暂停吊装"},
    "construction": {"name": "施工智能体", "domain": "construction", "owner": "Construction Manager / 施工经理",
                     "action": "Re-sequence the workface and brief the crew on the corrective measure / 调整作业面安排并向班组交底整改措施"},
}


class GateError(PermissionError):
    pass


class StateError(RuntimeError):
    pass


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _human(actor: str) -> str:
    actor = (actor or "").strip()
    if len(actor) < 2 or actor.lower().startswith(HUMAN_FORBIDDEN):
        raise GateError("this step needs a named human, not an agent, model or automation")
    return actor


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


class FieldPilot:
    def __init__(self, store: Store | None = None, model: Model | None = None, clock: Callable[[], datetime] | None = None,
                 assets_path: Path = ASSETS) -> None:
        self.store = store or Store()
        self.model = model
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        registry = json.loads(Path(assets_path).read_text(encoding="utf-8"))
        self.project = registry["project"]["code"]
        self.assets = {a["id"]: a for a in registry["assets"]}
        self.index = KnowledgeIndex(load_packs(PACKS))

    def now(self) -> str:
        return _iso(self.clock())

    def _audit(self, c, event_id, actor, action, detail) -> None:
        c.execute("INSERT INTO audit(event_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                  (event_id, actor, action, json.dumps(detail, ensure_ascii=False, default=str), self.now()))

    # --- sense -----------------------------------------------------------------------
    def store_media(self, content: bytes) -> dict:
        if len(content) > MAX_MEDIA:
            raise ValueError("file too large")
        media_type = sniff(content)
        if media_type is None:
            raise ValueError("unsupported file signature (JPEG, PNG, WebP, WAV or MP4)")
        sha = hashlib.sha256(content).hexdigest()
        facts = exif_facts(content) if media_type.startswith("image/") else {}
        ph = dhash(content) if media_type.startswith("image/") else None
        with self.store.tx() as c:
            c.execute("INSERT OR IGNORE INTO media(sha256,media_type,size,dhash,captured_at,lat,lon,content,received_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (sha, media_type, len(content), ph, facts.get("captured_at"), facts.get("lat"), facts.get("lon"), content, self.now()))
        return self.media(sha)

    def media(self, sha: str, with_content: bool = False) -> dict:
        cols = "*" if with_content else "sha256,media_type,size,dhash,captured_at,lat,lon,received_at"
        row = self.store.one(f"SELECT {cols} FROM media WHERE sha256=?", (sha,))
        if not row:
            raise KeyError(sha)
        return row

    def locate(self, text: str, asset_id: str | None, qr: str | None, lat: float | None, lon: float | None,
               photo: dict | None) -> tuple[str | None, str]:
        if asset_id:
            if asset_id not in self.assets:
                raise ValueError(f"unknown asset {asset_id}")
            return asset_id, "selected"
        if qr and qr.lower().startswith("asset:") and qr[6:].strip().upper() in self.assets:
            return qr[6:].strip().upper(), "qr"
        upper = text.upper()
        for aid in sorted(self.assets, key=len, reverse=True):
            if aid in upper:
                return aid, "text"
        point = (lat, lon) if lat is not None and lon is not None else ((photo["lat"], photo["lon"]) if photo and photo.get("lat") is not None else None)
        if point:
            nearest = min(self.assets.values(), key=lambda a: distance_m(point[0], point[1], a["lat"], a["lon"]))
            if distance_m(point[0], point[1], nearest["lat"], nearest["lon"]) <= nearest["geofence_m"]:
                return nearest["id"], "gps" if lat is not None else "photo_gps"
        return None, "unlocated"

    # --- assess + plan ----------------------------------------------------------------
    def report(self, *, description: str, reporter: str, reported_risk: str = "AUTO", asset_id: str | None = None, qr: str | None = None,
               lat: float | None = None, lon: float | None = None, photos: list[str] | None = None) -> dict:
        reporter = (reporter or "").strip() or "field user"
        photos = photos or []
        media = [self.media(s) for s in photos]
        asset, method = self.locate(description, asset_id, qr, lat, lon, next((m for m in media if m.get("lat") is not None), None))
        text_risk, signals = assess(description)
        vision_risk, vision_labels = None, []
        for m in media:
            v = vision_hazards(self.model, self.media(m["sha256"], True)["content"], m["media_type"], description)
            if v and v["hazards"]:
                vision_labels += [h["label"] for h in v["hazards"]]
                vision_risk = higher(vision_risk or "LOW", *(HAZARD_TAXONOMY[h["label"]] for h in v["hazards"]))
        final = higher(reported_risk, text_risk, vision_risk or "LOW")
        respond, close = SLA_HOURS[final]
        created = self.clock()
        eid = "EVT-" + uuid.uuid4().hex[:10].upper()
        signals_all = signals + [f"vision:{v}" for v in vision_labels]
        with self.store.tx() as c:
            c.execute("INSERT INTO events(id,project,description,asset_id,asset_method,reported_risk,text_risk,vision_risk,final_risk,signals,"
                      "stop_work,status,reporter,lat,lon,response_due,close_due,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (eid, self.project, description, asset, method, reported_risk, text_risk, vision_risk, final, json.dumps(signals_all, ensure_ascii=False),
                       int(stop_work(final, signals)), "REPORTED", reporter, lat, lon, _iso(created + timedelta(hours=respond)),
                       _iso(created + timedelta(hours=close)), _iso(created), _iso(created)))
            for s in photos:
                c.execute("INSERT OR IGNORE INTO event_media VALUES(?,?,?,?,?)", (eid, s, "before", reporter, self.now()))
            self._audit(c, eid, reporter, "event.reported", {"risk": final, "signals": signals_all, "asset": asset, "located_by": method})
        return self.analyse(eid)

    def _domains(self, sid: str) -> set[str]:
        spec = SPECIALISTS[sid]
        return {spec["domain"], *spec.get("also", [])}

    def route(self, text: str, risk: str) -> tuple[list[str], list[dict]]:
        """Specialists whose domain the governed evidence points to; HSE joins any HIGH/CRITICAL event."""
        hits = self.index.search(text, top_k=10)
        best: dict[str, float] = {}
        for sid in SPECIALISTS:
            scores = [h["score"] for h in hits if h["domain"] in self._domains(sid)]
            if scores:
                best[sid] = max(scores)
        top = max(best.values(), default=0.0)
        team = sorted((sid for sid, score in best.items() if score >= 0.6 * top), key=lambda sid: -best[sid])
        if risk in {"HIGH", "CRITICAL"} and "hse" not in team:
            team.append("hse")
        return (team or ["construction"])[:3], hits

    def analyse(self, event_id: str) -> dict:
        ev = self._event_row(event_id)
        if ev["status"] not in {"REPORTED", "ASSESSED"}:
            raise StateError(f"event is {ev['status']}; analysis is frozen after approval")
        team, hits = self.route(ev["description"], ev["final_risk"])
        due = _iso(_parse(ev["created_at"]) + timedelta(hours=SLA_HOURS[ev["final_risk"]][1]))
        with self.store.tx() as c:
            c.execute("DELETE FROM findings WHERE event_id=?", (event_id,))
            c.execute("DELETE FROM tasks WHERE event_id=? AND status='PROPOSED'", (event_id,))
            for sid in team:
                spec = SPECIALISTS[sid]
                own = [h for h in hits if h["domain"] in self._domains(sid)][:3]
                if own:
                    top = own[0]
                    confidence = round(min(0.95, 0.55 + 0.04 * top["score"]), 2)
                    claim = f"{spec['name']}：{top['title']}（{top['ref']}）— {top['text'][:160]}"
                    c.execute("INSERT INTO findings(event_id,agent_id,status,claim,evidence_refs,confidence,questions) VALUES(?,?,?,?,?,?,?)",
                              (event_id, sid, "SUPPORTED", claim, json.dumps([h["ref"] for h in own]), confidence, "[]"))
                    c.execute("INSERT INTO tasks(id,event_id,title,owner_role,source,evidence_refs,status,due_at) VALUES(?,?,?,?,?,?,?,?)",
                              ("TSK-" + uuid.uuid4().hex[:8].upper(), event_id, spec["action"], spec["owner"], f"finding:{sid}",
                               json.dumps([h["ref"] for h in own]), "PROPOSED", due))
                else:
                    c.execute("INSERT INTO findings(event_id,agent_id,status,claim,evidence_refs,confidence,questions) VALUES(?,?,?,?,?,?,?)",
                              (event_id, sid, "GAP", f"{spec['name']}：没有找到适用的受控依据 / no governed source found", "[]", 0.3,
                               json.dumps(["请补充适用的规程、方案或记录 / Which procedure or record governs this?"], ensure_ascii=False)))
            c.execute("UPDATE events SET status='ASSESSED', updated_at=? WHERE id=?", (self.now(), event_id))
            self._audit(c, event_id, "system", "event.assessed", {"team": team})
        return self.event(event_id)

    # --- human gate, dispatch, rectification ------------------------------------------------
    def approve(self, event_id: str, actor: str) -> dict:
        actor = _human(actor)
        with self.store.tx() as c:
            cur = c.execute("UPDATE events SET status='APPROVED', updated_at=? WHERE id=? AND status='ASSESSED'", (self.now(), event_id))
            if cur.rowcount != 1:
                raise StateError("only an assessed event can be approved")
            if not c.execute("SELECT 1 FROM tasks WHERE event_id=? AND status='PROPOSED'", (event_id,)).fetchone():
                raise StateError("no evidence-backed task to approve; answer the agents' questions first")
            c.execute("UPDATE tasks SET status='APPROVED' WHERE event_id=? AND status='PROPOSED'", (event_id,))
            self._audit(c, event_id, actor, "plan.approved", {})
            self._receipt(c, event_id, "approval", "APPROVED", {"approved_by": actor})
        return self.event(event_id)

    def dispatch(self, event_id: str, actor: str) -> dict:
        actor = _human(actor)
        with self.store.tx() as c:
            cur = c.execute("UPDATE events SET status='DISPATCHED', updated_at=? WHERE id=? AND status='APPROVED'", (self.now(), event_id))
            if cur.rowcount != 1:
                raise GateError("human approval is required before dispatch")
            c.execute("UPDATE tasks SET status='DISPATCHED' WHERE event_id=? AND status='APPROVED'", (event_id,))
            tasks = [dict(r) for r in c.execute("SELECT id,title,owner_role,due_at FROM tasks WHERE event_id=?", (event_id,))]
            self._receipt(c, event_id, "dispatch", "DISPATCHED", {"dispatched_by": actor, "tasks": tasks, "external_side_effect": False})
            self._audit(c, event_id, actor, "tasks.dispatched", {"count": len(tasks)})
        return self.event(event_id)

    def complete_task(self, task_id: str, actor: str, note: str) -> dict:
        actor = _human(actor)
        task = self.store.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not task:
            raise KeyError(task_id)
        with self.store.tx() as c:
            cur = c.execute("UPDATE tasks SET status='DONE', done_by=?, done_at=?, note=? WHERE id=? AND status='DISPATCHED'",
                            (actor, self.now(), note, task_id))
            if cur.rowcount != 1:
                raise StateError("only a dispatched task can be completed")
            self._audit(c, task["event_id"], actor, "task.done", {"task": task_id, "note": note})
        return self.event(task["event_id"])

    # --- re-inspection and verification ------------------------------------------------------
    def reinspect(self, event_id: str, *, inspector: str, observation: str, resolved: bool, photos: list[str],
                  attest_location: bool = False) -> dict:
        inspector = _human(inspector)
        ev = self._event_row(event_id)
        if ev["status"] not in {"DISPATCHED", "VERIFICATION_FAILED"}:
            raise StateError("re-inspection follows dispatch")
        after = [self.media(s) for s in photos]
        before = [self.media(r["sha256"]) for r in self.store.rows("SELECT sha256 FROM event_media WHERE event_id=? AND role='before'", (event_id,))]
        tasks = self.store.rows("SELECT * FROM tasks WHERE event_id=?", (event_id,))
        dispatch = self.store.one("SELECT created_at FROM receipts WHERE event_id=? AND kind='dispatch'", (event_id,))
        dispatched_at = _parse(dispatch["created_at"]) if dispatch else None
        asset = self.assets.get(ev["asset_id"] or "")
        images = [m for m in after if m["media_type"].startswith("image/")]

        def taken(m):
            return _parse(m["captured_at"]) if m.get("captured_at") else _parse(m["received_at"])

        reused = [m["sha256"][:12] for m in images for b in before
                  if m["sha256"] == b["sha256"] or (m["dhash"] and b.get("dhash") and hamming(m["dhash"], b["dhash"]) <= REUSE_DISTANCE)]
        located = [m for m in images if m.get("lat") is not None]
        at_asset = bool(asset) and bool(located) and all(distance_m(m["lat"], m["lon"], asset["lat"], asset["lon"]) <= asset["geofence_m"] for m in located)
        executors = {t["done_by"] for t in tasks if t["done_by"]}
        hazard_cleared = resolved
        if self.model is not None:
            for m in images:
                v = vision_hazards(self.model, self.media(m["sha256"], True)["content"], m["media_type"], observation)
                if v and v["hazards"]:
                    hazard_cleared = False
        checks = {
            "all_tasks_done": bool(tasks) and all(t["status"] == "DONE" for t in tasks),
            "after_photo_present": bool(images),
            "after_photo_is_new": bool(images) and not reused,
            "after_photo_after_dispatch": bool(images) and dispatched_at is not None and all(taken(m) >= dispatched_at for m in images),
            "after_photo_at_asset": at_asset or (attest_location and bool(asset)),
            "inspector_independent": inspector not in executors and inspector != ev["reporter"],
            "hazard_cleared": hazard_cleared,
        }
        passed = all(checks.values())
        payload = {"inspector": inspector, "observation": observation, "checks": checks, "passed": passed,
                   "location_basis": "photo_gps" if at_asset else ("inspector_attestation" if attest_location else "none"),
                   "reused_photos": reused, "after_photos": [m["sha256"] for m in after]}
        with self.store.tx() as c:
            for s in photos:
                c.execute("INSERT OR IGNORE INTO event_media VALUES(?,?,?,?,?)", (event_id, s, "after", inspector, self.now()))
            self._receipt(c, event_id, "verification", "PASSED" if passed else "FAILED", payload)
            c.execute("UPDATE events SET status=?, updated_at=? WHERE id=?", ("VERIFIED" if passed else "VERIFICATION_FAILED", self.now(), event_id))
            self._audit(c, event_id, inspector, "reinspection.verified" if passed else "reinspection.failed", checks)
        return self.event(event_id)

    def close(self, event_id: str, actor: str) -> dict:
        actor = _human(actor)
        with self.store.tx() as c:
            cur = c.execute("UPDATE events SET status='CLOSED', closed_at=?, updated_at=? WHERE id=? AND status='VERIFIED'",
                            (self.now(), self.now(), event_id))
            if cur.rowcount != 1:
                raise GateError("an event closes only after a passed independent re-inspection")
            self._audit(c, event_id, actor, "event.closed", {})
        return self.event(event_id)

    def _receipt(self, c, event_id: str, kind: str, status: str, payload: dict) -> None:
        c.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?)", ("RCP-" + uuid.uuid4().hex[:10].upper(), event_id, kind, status,
                                                                 _digest(payload), json.dumps(payload, ensure_ascii=False), self.now()))

    # --- read models -----------------------------------------------------------------------
    def _event_row(self, event_id: str) -> dict:
        ev = self.store.one("SELECT * FROM events WHERE id=?", (event_id,))
        if not ev:
            raise KeyError(event_id)
        return ev

    def event(self, event_id: str) -> dict:
        ev = self._event_row(event_id)
        ev["signals"] = json.loads(ev["signals"])
        ev["stop_work"] = bool(ev["stop_work"])
        ev["asset"] = self.assets.get(ev["asset_id"] or "")
        ev["findings"] = [{**f, "evidence_refs": json.loads(f["evidence_refs"]), "questions": json.loads(f["questions"])}
                          for f in self.store.rows("SELECT * FROM findings WHERE event_id=? ORDER BY id", (event_id,))]
        ev["tasks"] = [{**t, "evidence_refs": json.loads(t["evidence_refs"])} for t in self.store.rows("SELECT * FROM tasks WHERE event_id=? ORDER BY id", (event_id,))]
        ev["media"] = [{**self.media(r["sha256"]), "role": r["role"]} for r in self.store.rows("SELECT * FROM event_media WHERE event_id=? ORDER BY added_at", (event_id,))]
        ev["receipts"] = [{**r, "payload": json.loads(r["payload"])} for r in self.store.rows("SELECT * FROM receipts WHERE event_id=? ORDER BY created_at", (event_id,))]
        ev["audit"] = self.store.rows("SELECT actor,action,detail,created_at FROM audit WHERE event_id=? ORDER BY id", (event_id,))
        now = self.clock()
        ev["sla"] = {"response_overdue": ev["status"] in {"REPORTED", "ASSESSED"} and now > _parse(ev["response_due"]),
                     "close_overdue": ev["status"] != "CLOSED" and now > _parse(ev["close_due"])}
        ev["precedents"] = self.precedents(ev)
        return ev

    def precedents(self, ev: dict) -> list[dict]:
        """Closed events on the same asset or with a shared signal: what was done and how long it took."""
        out = []
        signals = set(json.loads(ev["signals"]) if isinstance(ev["signals"], str) else ev["signals"])
        for p in self.store.rows("SELECT * FROM events WHERE status='CLOSED' AND id!=? ORDER BY closed_at DESC LIMIT 50", (ev["id"],)):
            shared = signals & set(json.loads(p["signals"]))
            if p["asset_id"] == ev["asset_id"] and ev["asset_id"] or shared:
                hours = (_parse(p["closed_at"]) - _parse(p["created_at"])).total_seconds() / 3600
                tasks = [t["title"] for t in self.store.rows("SELECT title FROM tasks WHERE event_id=?", (p["id"],))]
                out.append({"id": p["id"], "asset_id": p["asset_id"], "risk": p["final_risk"], "shared_signals": sorted(shared),
                            "hours_to_close": round(hours, 1), "actions": tasks, "description": p["description"][:120]})
        return out[:5]

    def board(self, limit: int = 50) -> list[dict]:
        now = self.clock()
        rows = self.store.rows("SELECT id,description,asset_id,final_risk,status,stop_work,response_due,close_due,created_at FROM events ORDER BY created_at DESC LIMIT ?", (limit,))
        for r in rows:
            r["close_overdue"] = r["status"] != "CLOSED" and now > _parse(r["close_due"])
        return rows

    def dashboard(self) -> dict:
        events = self.store.rows("SELECT * FROM events")
        closed = [e for e in events if e["status"] == "CLOSED"]
        verifications = self.store.rows("SELECT event_id,status,created_at FROM receipts WHERE kind='verification' ORDER BY created_at")
        first = {}
        for v in verifications:
            first.setdefault(v["event_id"], v["status"])
        hotspots: dict[str, int] = {}
        for e in events:
            if e["asset_id"]:
                hotspots[e["asset_id"]] = hotspots.get(e["asset_id"], 0) + 1
        now = self.clock()
        return {
            "events": len(events),
            "by_status": {s: sum(e["status"] == s for e in events) for s in sorted({e["status"] for e in events})},
            "by_risk": {r: sum(e["final_risk"] == r for e in events) for r in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
            "stop_work_active": sum(e["stop_work"] and e["status"] != "CLOSED" for e in events),
            "overdue": [e["id"] for e in events if e["status"] != "CLOSED" and now > _parse(e["close_due"])],
            "closed_within_sla": round(sum(_parse(e["closed_at"]) <= _parse(e["close_due"]) for e in closed) / len(closed), 3) if closed else None,
            "mean_hours_to_close": round(sum((_parse(e["closed_at"]) - _parse(e["created_at"])).total_seconds() for e in closed) / 3600 / len(closed), 1) if closed else None,
            "verification_first_pass_rate": round(sum(v == "PASSED" for v in first.values()) / len(first), 3) if first else None,
            "hotspots": sorted(hotspots.items(), key=lambda kv: -kv[1])[:5],
        }
