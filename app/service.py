from __future__ import annotations
import hashlib, json, mimetypes, re, uuid
from datetime import datetime, timezone
from .db import tx, connect
from .risk import assess_text, higher
from .agents import assemble, SOURCE_TEXT
from .llm import vision_assess

NOW=lambda: datetime.now(timezone.utc).isoformat()

def jid(prefix:str)->str: return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"

def rowdict(row): return dict(row) if row is not None else None

def _json(v): return json.dumps(v, ensure_ascii=False, sort_keys=True)

def audit(conn,event_id,actor,action,detail):
    conn.execute("INSERT INTO audit_events(event_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",(event_id,actor,action,_json(detail),NOW()))

def sniff(content:bytes)->str|None:
    h=content[:16]
    if h.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    if h.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if h[:4]==b'RIFF' and h[8:12]==b'WEBP': return 'image/webp'
    if h[:4]==b'RIFF' and h[8:12]==b'WAVE': return 'audio/wav'
    if h[4:8]==b'ftyp': return 'video/mp4'
    if h.startswith(b'ID3') or h[:2] in (b'\xff\xfb',b'\xff\xf3',b'\xff\xf2'): return 'audio/mpeg'
    return None

def store_media(content:bytes, declared:str|None=None)->dict:
    media_type=sniff(content)
    if media_type is None: raise ValueError('unsupported media signature')
    sha=hashlib.sha256(content).hexdigest()
    with tx() as conn:
        conn.execute("INSERT OR IGNORE INTO media(sha256,media_type,size,content,created_at) VALUES(?,?,?,?,?)",(sha,media_type,len(content),content,NOW()))
    return {"sha256":sha,"media_type":media_type,"size":len(content)}

async def create_event(payload:dict)->dict:
    project_id=int(payload.get('project_id',1)); media_sha=payload.get('media_sha')
    description=payload['description'].strip(); reported=payload.get('reported_risk','AUTO')
    ai_risk,hits=assess_text(description); perception_method='rules'
    if media_sha:
        with connect() as c: m=c.execute("SELECT * FROM media WHERE sha256=?",(media_sha,)).fetchone()
        if not m: raise ValueError('media not found')
        v=await vision_assess(bytes(m['content']),m['media_type'],description)
        if v and v.get('risk') in {"LOW","MEDIUM","HIGH","CRITICAL"}:
            ai_risk=higher(ai_risk,v['risk']); perception_method='vision_model'
    final=higher(reported,ai_risk)
    event_id=jid('EVT'); now=NOW()
    with tx() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id=?",(project_id,)).fetchone(): raise ValueError('project not found')
        conn.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            event_id,project_id,'field',description,payload.get('event_type','observation'),reported,ai_risk,final,payload.get('asset_ref'),payload.get('lat'),payload.get('lon'),'NEW',perception_method,now,now))
        if media_sha: conn.execute("INSERT INTO event_media(event_id,media_sha,role) VALUES(?,?,?)",(event_id,media_sha,'before'))
        audit(conn,event_id,'reporter','event.created',{"risk_rules":hits,"perception_method":perception_method})
    return get_event(event_id)

def get_event(event_id:str)->dict:
    with connect() as conn:
        e=conn.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not e: raise KeyError(event_id)
        out=rowdict(e)
        for key in ('findings','actions','receipts','inspections'):
            table={'findings':'findings','actions':'actions','receipts':'receipts','inspections':'inspections'}[key]
            rows=[rowdict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE event_id=? ORDER BY rowid",(event_id,)).fetchall()]
            for r in rows:
                for fld in ('evidence_refs','actions','questions','payload'):
                    if fld in r and isinstance(r[fld],str):
                        try:r[fld]=json.loads(r[fld])
                        except:pass
            out[key]=rows
        d=conn.execute("SELECT * FROM decisions WHERE event_id=? ORDER BY created_at DESC LIMIT 1",(event_id,)).fetchone()
        out['decision']=rowdict(d)
        if out['decision']:
            out['decision']['plan']=json.loads(out['decision']['plan'])
        out['media']=[dict(r) for r in conn.execute("SELECT em.role,m.sha256,m.media_type,m.size FROM event_media em JOIN media m ON m.sha256=em.media_sha WHERE em.event_id=?",(event_id,)).fetchall()]
        return out

def analyze(event_id:str)->dict:
    with tx() as conn:
        e=conn.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not e: raise KeyError(event_id)
        conn.execute("DELETE FROM findings WHERE event_id=?",(event_id,))
        team=assemble(e['description'],e['final_risk'])
        findings=[]; plan=[]
        for a in team:
            refs=list(a.evidence[:1])
            claim=f"{a.name}: {a.focus} requires review for this event."
            actions=[a.action]
            questions=[]
            if a.id in {'engineering','quality'} and not e['asset_ref']:
                questions=["Confirm the affected asset/component reference."]
            conn.execute("INSERT INTO findings(event_id,agent_id,claim,status,evidence_refs,confidence,actions,questions,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id,a.id,claim,'SUPPORTED',_json(refs),0.86,_json(actions),_json(questions),NOW()))
            findings.append({"agent_id":a.id,"agent":a.name,"claim":claim,"status":"SUPPORTED","evidence_refs":refs,"confidence":0.86,"actions":actions,"questions":questions})
            plan.append({"title":a.action,"owner":a.owner,"source":f"finding:{a.id}","evidence_refs":refs})
        # deduplicate exact actions
        uniq=[]; seen=set()
        for p in plan:
            if p['title'] not in seen: uniq.append(p); seen.add(p['title'])
        decision_id=jid('DEC')
        conn.execute("INSERT INTO decisions VALUES(?,?,?,?,?)",(decision_id,event_id,_json(uniq),'AWAITING_APPROVAL',NOW()))
        conn.execute("DELETE FROM actions WHERE event_id=?",(event_id,))
        for p in uniq:
            conn.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?,?,?)",(jid('ACT'),event_id,p['title'],p['owner'],'AWAITING_APPROVAL',1,None,NOW(),None,None))
        conn.execute("UPDATE events SET status='AWAITING_APPROVAL',updated_at=? WHERE id=?",(NOW(),event_id))
        audit(conn,event_id,'system','analysis.completed',{"team":[a.id for a in team],"findings":len(findings),"plan_steps":len(uniq)})
    return get_event(event_id)

def approve(event_id:str,actor:str)->dict:
    with tx() as conn:
        e=conn.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not e: raise KeyError(event_id)
        if e['status']!='AWAITING_APPROVAL': raise ValueError('event is not awaiting approval')
        conn.execute("UPDATE actions SET status='APPROVED',approved_by=? WHERE event_id=?",(actor,event_id))
        conn.execute("UPDATE decisions SET status='APPROVED' WHERE event_id=?",(event_id,))
        conn.execute("UPDATE events SET status='APPROVED',updated_at=? WHERE id=?",(NOW(),event_id))
        audit(conn,event_id,actor,'decision.approved',{})
    return get_event(event_id)

def dispatch(event_id:str,actor:str)->dict:
    with tx() as conn:
        e=conn.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not e: raise KeyError(event_id)
        if e['status']!='APPROVED': raise ValueError('human approval required')
        rows=conn.execute("SELECT * FROM actions WHERE event_id=?",(event_id,)).fetchall()
        for a in rows:
            payload={"action_id":a['id'],"title":a['title'],"owner":a['owner'],"delivery_status":"DISPATCHED_TO_DEMO_QUEUE","external_side_effect":False}
            digest=hashlib.sha256(_json(payload).encode()).hexdigest()
            conn.execute("UPDATE actions SET status='DISPATCHED',dispatched_at=?,executed_at=? WHERE id=?",(NOW(),NOW(),a['id']))
            conn.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?)",(jid('RCP'),event_id,a['id'],'execution','SUCCEEDED',digest,_json(payload),NOW()))
        conn.execute("UPDATE events SET status='EXECUTED',updated_at=? WHERE id=?",(NOW(),event_id))
        audit(conn,event_id,actor,'actions.dispatched',{"count":len(rows),"external_side_effect":False})
    return get_event(event_id)

def reinspect(event_id:str,observation:str,resolved:bool,media_sha:str|None,actor:str)->dict:
    with tx() as conn:
        e=conn.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not e: raise KeyError(event_id)
        if e['status']!='EXECUTED': raise ValueError('execute approved actions before re-inspection')
        if media_sha and not conn.execute("SELECT 1 FROM media WHERE sha256=?",(media_sha,)).fetchone(): raise ValueError('media not found')
        iid=jid('INSP')
        conn.execute("INSERT INTO inspections VALUES(?,?,?,?,?,?)",(iid,event_id,observation,media_sha,1 if resolved else 0,NOW()))
        if media_sha: conn.execute("INSERT OR IGNORE INTO event_media(event_id,media_sha,role) VALUES(?,?,?)",(event_id,media_sha,'after'))
        checks={"human_reinspection":True,"resolution_asserted":resolved,"execution_receipt":bool(conn.execute("SELECT 1 FROM receipts WHERE event_id=? AND kind='execution' AND status='SUCCEEDED'",(event_id,)).fetchone()),"after_evidence":bool(media_sha or observation)}
        passed=all(checks.values())
        payload={"inspection_id":iid,"checks":checks,"passed":passed,"actor":actor}
        digest=hashlib.sha256(_json(payload).encode()).hexdigest()
        conn.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?)",(jid('RCP'),event_id,None,'verification','PASSED' if passed else 'FAILED',digest,_json(payload),NOW()))
        conn.execute("UPDATE events SET status=?,updated_at=? WHERE id=?",('VERIFIED' if passed else 'VERIFICATION_FAILED',NOW(),event_id))
        audit(conn,event_id,actor,'reinspection.verified',payload)
    return get_event(event_id)

def close(event_id:str,actor:str='project_manager')->dict:
    with tx() as conn:
        e=conn.execute("SELECT * FROM events WHERE id=?",(event_id,)).fetchone()
        if not e: raise KeyError(event_id)
        if e['status']!='VERIFIED': raise ValueError('verification must pass before close')
        conn.execute("UPDATE events SET status='CLOSED',updated_at=? WHERE id=?",(NOW(),event_id))
        audit(conn,event_id,actor,'event.closed',{})
    return get_event(event_id)

def dashboard()->dict:
    with connect() as conn:
        counts={r['status']:r['n'] for r in conn.execute("SELECT status,COUNT(*) n FROM events GROUP BY status")}
        risks={r['final_risk']:r['n'] for r in conn.execute("SELECT final_risk,COUNT(*) n FROM events GROUP BY final_risk")}
        recent=[dict(r) for r in conn.execute("SELECT id,description,final_risk,status,created_at FROM events ORDER BY created_at DESC LIMIT 10")]
        return {"events_by_status":counts,"events_by_risk":risks,"recent":recent}
