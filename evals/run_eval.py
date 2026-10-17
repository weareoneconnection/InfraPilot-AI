from __future__ import annotations
import json
from pathlib import Path
from app.risk import assess_text
from app.agents import assemble

rows=[json.loads(x) for x in (Path(__file__).parent.parent/'data/synthetic_events.jsonl').read_text().splitlines() if x.strip()]
results=[]
for r in rows:
    risk,_=assess_text(r['text']); team=[a.id for a in assemble(r['text'],risk)]
    results.append({'id':r['id'],'risk_ok':risk==r['expected_risk'],'agent_ok':r['expected_agent'] in team,'risk':risk,'team':team})
metrics={'risk_accuracy':sum(x['risk_ok'] for x in results)/len(results),'routing_accuracy':sum(x['agent_ok'] for x in results)/len(results)}
passed=all(v>=0.8 for v in metrics.values())
print(json.dumps({'suite':'INFRAPILOT_FIELD','status':'PASSED' if passed else 'FAILED','metrics':metrics,'cases':results},ensure_ascii=False,indent=2))
raise SystemExit(0 if passed else 1)
