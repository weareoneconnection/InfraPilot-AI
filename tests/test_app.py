import os, tempfile
os.environ['INFRAPILOT_DB']=tempfile.mktemp(suffix='.db')
from fastapi.testclient import TestClient
from app.main import app


def test_golden_closed_loop():
    with TestClient(app) as c:
        r=c.post('/demo/golden',json={'description':'Worker near unprotected edge at Pier P47, work continues today.','asset_ref':'PIER-P47'})
        assert r.status_code==200
        e=r.json()['event']
        assert e['status']=='CLOSED'
        assert e['final_risk'] in {'HIGH','CRITICAL'}
        assert e['findings']
        assert any(x['kind']=='execution' for x in e['receipts'])
        assert any(x['kind']=='verification' and x['status']=='PASSED' for x in e['receipts'])


def test_cannot_dispatch_without_human_approval():
    with TestClient(app) as c:
        e=c.post('/events',json={'description':'Crack found on pier P52','reported_risk':'MEDIUM'}).json()
        e=c.post(f"/events/{e['id']}/analyze").json()
        r=c.post(f"/events/{e['id']}/dispatch",json={'actor':'tester'})
        assert r.status_code==409
