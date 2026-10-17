from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Agent:
    id: str
    name: str
    focus: str
    keywords: tuple[str,...]
    evidence: tuple[str,...]
    action: str
    owner: str

AGENTS = {
    "hse": Agent("hse","HSE Agent","safety hazards",("edge","height","fall","crane","lifting","临边","高处","吊装"),("HSE-WAH-001","HSE-LIFT-001"),"Stop unsafe exposure and verify controls before restart","HSE Manager"),
    "quality": Agent("quality","Quality Agent","defects and inspection",("crack","ncr","defect","裂缝","不符合","缺陷"),("QA-CONCRETE-001","QA-ITP-001"),"Raise an inspection/NCR workflow and define corrective evidence","QA/QC Manager"),
    "construction": Agent("construction","Construction Agent","workface execution",("work","crew","continue","access","施工","班组","继续"),("CONST-METHOD-001",),"Re-sequence the workface and brief the responsible crew","Construction Manager"),
    "engineering": Agent("engineering","Engineering Agent","technical causation",("pier","beam","structure","crack","构件","墩","梁","裂缝"),("ENG-ASSESS-001",),"Confirm asset condition and engineering acceptance criteria","Lead Engineer"),
    "planning": Agent("planning","Planning Agent","schedule impact",("today","tomorrow","delay","continue","下午","明天","延误"),("PLAN-RECOVERY-001",),"Assess schedule exposure and recovery options","Planning Manager"),
    "plant": Agent("plant","Plant Agent","plant and lifting readiness",("crane","lifting","equipment","起重机","吊装","设备"),("PLANT-CERT-001",),"Check equipment certification and lifting readiness","Plant Manager"),
}

SOURCE_TEXT = {
    "HSE-WAH-001":"Synthetic reference: work-at-height exposure requires edge protection or a controlled fall-protection system before work proceeds.",
    "HSE-LIFT-001":"Synthetic reference: lifting activities require an approved lift plan, competent people and certified equipment.",
    "QA-CONCRETE-001":"Synthetic reference: structural concrete defects require location, dimensions, inspection record and engineering disposition before closure.",
    "QA-ITP-001":"Synthetic reference: inspection hold points must be released with recorded evidence.",
    "CONST-METHOD-001":"Synthetic reference: workface controls and approved method statements govern site execution.",
    "ENG-ASSESS-001":"Synthetic reference: engineering acceptance must be based on asset-specific facts and approved criteria.",
    "PLAN-RECOVERY-001":"Synthetic reference: schedule recovery decisions require impact, dependency and next-gate review.",
    "PLANT-CERT-001":"Synthetic reference: plant used in critical operations requires valid inspection/certification evidence.",
}

def assemble(text: str, risk: str) -> list[Agent]:
    lower=text.lower(); selected=[]
    for a in AGENTS.values():
        if any(k.lower() in lower for k in a.keywords): selected.append(a)
    if risk in {"HIGH","CRITICAL"} and AGENTS["hse"] not in selected: selected.insert(0,AGENTS["hse"])
    if not selected: selected=[AGENTS["construction"],AGENTS["engineering"]]
    # keep a concise expert team
    seen=[]
    for a in selected:
        if a.id not in {x.id for x in seen}: seen.append(a)
    return seen[:5]
