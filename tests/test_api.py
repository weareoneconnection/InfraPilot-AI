from fastapi.testclient import TestClient


def test_api_closed_loop():
    from app.main import app
    with TestClient(app) as c:
        before = c.post("/demo/photo", params={"scene": "before", "asset_id": "P47"}).json()["sha256"]
        e = c.post("/events", json={"description": "P47墩临边防护缺失，工人未系安全带", "reporter": "班组长 李明", "photos": [before]}).json()
        eid = e["id"]
        assert c.post(f"/events/{eid}/dispatch", json={"actor": "现场经理 王工"}).status_code == 403
        assert c.post(f"/events/{eid}/approve", json={"actor": "model:x"}).status_code == 403
        assert c.post(f"/events/{eid}/approve", json={"actor": "项目经理 张工"}).status_code == 200
        e = c.post(f"/events/{eid}/dispatch", json={"actor": "现场经理 王工"}).json()
        for t in e["tasks"]:
            c.post(f"/tasks/{t['id']}/done", json={"actor": "整改班组 陈工", "note": "ok"})
        reused = c.post(f"/events/{eid}/reinspect", json={"inspector": "安全员 周工", "observation": "复检", "resolved": True, "photos": [before]}).json()
        assert reused["status"] == "VERIFICATION_FAILED"
        after = c.post("/demo/photo", params={"scene": "after", "asset_id": "P47", "minutes_from_now": 1}).json()["sha256"]
        ok = c.post(f"/events/{eid}/reinspect", json={"inspector": "安全员 周工", "observation": "复检合格", "resolved": True, "photos": [after]}).json()
        assert ok["status"] == "VERIFIED"
        assert c.post(f"/events/{eid}/close", json={"actor": "项目经理 张工"}).json()["status"] == "CLOSED"
        assert c.get(f"/media/{after}").headers["content-type"] == "image/jpeg"
        assert c.post("/media", files={"file": ("x.html", b"<html>", "text/html")}).status_code == 415
        assert c.get("/dashboard").json()["events"] >= 1
        assert c.get("/").status_code == 200


def test_mcp_tools(tmp_path):
    import asyncio
    import json

    from mcp import Client

    from app.mcp_server import EXPOSED, build_server
    from app.service import FieldPilot
    from app.store import Store

    async def go():
        async with Client(build_server(FieldPilot(Store(tmp_path / "m.db")))) as client:
            assert {t.name for t in (await client.list_tools()).tools} == set(EXPOSED)
            e = json.loads((await client.call_tool("report_observation", {"description": "BRG-03支座锈蚀和位移超过预警值"})).content[0].text)
            assert e["asset_id"] == "BRG-03" and e["status"] == "ASSESSED"

    asyncio.run(go())
