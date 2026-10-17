import sqlite3

from app.service import FieldPilot
from app.store import Store


class Scripted:
    def __init__(self, hazards=None, finding=None):
        self.hazards, self.finding = hazards, finding

    def complete_json(self, system, user, schema):
        assert "<data>" in user
        return {"text_hazards": self.hazards, "field_finding": self.finding}.get(schema["title"])


def test_text_model_can_only_raise_risk_with_a_quote(tmp_path):
    fp = FieldPilot(Store(tmp_path / "a.db"), model=Scripted(hazards={"hazards": [
        {"label": "exposed_live_parts", "confidence": 0.9, "quote": "电缆外皮破损露出铜线"},
        {"label": "collapse", "confidence": 0.95, "quote": "整座桥塌了"}]}))
    e = fp.report(description="S07车站临时电缆外皮破损露出铜线，旁边有积水", reporter="x")
    assert e["final_risk"] == "CRITICAL" and e["model_risk"] == "CRITICAL"
    assert "model:exposed_live_parts" in e["signals"] and "model:collapse" not in e["signals"]


def test_model_label_must_be_named_by_its_quote(tmp_path):
    # A crack quoted as a "collapse" is discarded, so it cannot escalate to CRITICAL or stop work.
    fp = FieldPilot(Store(tmp_path / "c.db"), model=Scripted(hazards={"hazards": [
        {"label": "collapse", "confidence": 0.9, "quote": "混凝土出现裂缝"}]}))
    e = fp.report(description="P52墩柱混凝土出现裂缝", reporter="x")
    assert e["final_risk"] == "MEDIUM" and e["model_risk"] is None and not e["stop_work"]


def test_model_finding_must_cite_retrieved_sources(tmp_path):
    fp = FieldPilot(Store(tmp_path / "b.db"), model=Scripted(finding={"claim": "立即停止 P47 临边作业，设置防护栏杆后复工。",
                                                                  "evidence_refs": ["HSE-WAH-001", "FAKE-001"], "questions": []}))
    f = fp.report(description="P47墩临边防护缺失，工人在高处作业未系安全带", reporter="x")["findings"][0]
    assert f["composed_by"] == "model" and f["evidence_refs"] == ["HSE-WAH-001"]
    fp.model = Scripted(finding={"claim": "fine", "evidence_refs": ["FAKE-001"], "questions": []})
    f = fp.report(description="P47墩临边防护缺失，工人在高处作业未系安全带", reporter="x")["findings"][0]
    assert f["composed_by"] == "rules"


def test_databases_from_the_first_release_are_migrated(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE events(id TEXT PRIMARY KEY, project TEXT NOT NULL, description TEXT NOT NULL, asset_id TEXT, asset_method TEXT, "
                  "reported_risk TEXT NOT NULL, text_risk TEXT NOT NULL, vision_risk TEXT, final_risk TEXT NOT NULL, signals TEXT NOT NULL, "
                  "stop_work INTEGER NOT NULL, status TEXT NOT NULL, reporter TEXT NOT NULL, lat REAL, lon REAL, response_due TEXT NOT NULL, "
                  "close_due TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT)")
        c.execute("CREATE TABLE findings(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, agent_id TEXT NOT NULL, status TEXT NOT NULL, "
                  "claim TEXT NOT NULL, evidence_refs TEXT NOT NULL, confidence REAL NOT NULL, questions TEXT NOT NULL)")
    fp = FieldPilot(Store(path))
    assert fp.report(description="P47墩临边防护缺失", reporter="x")["findings"]
