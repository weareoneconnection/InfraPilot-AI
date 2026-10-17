from __future__ import annotations
import re

ORDER = ["LOW","MEDIUM","HIGH","CRITICAL"]

RULES = [
    ("CRITICAL", [r"fatal", r"collapse", r"electrocution", r"坍塌", r"触电", r"人员坠落"]),
    ("HIGH", [r"unprotected edge", r"working at height", r"fall protection", r"guardrail", r"crane", r"lifting", r"deep excavation", r"临边", r"高处作业", r"吊装", r"深基坑"]),
    ("MEDIUM", [r"crack", r"defect", r"spill", r"blocked access", r"access route blocked", r"裂缝", r"缺陷", r"泄漏", r"通道堵塞"]),
]

def assess_text(text: str) -> tuple[str,list[str]]:
    t=text.lower()
    hits=[]
    for risk, patterns in RULES:
        for p in patterns:
            if re.search(p,t,re.I):
                hits.append(p)
        if hits:
            return risk,hits
    return "LOW",[]

def higher(a: str, b: str) -> str:
    if a == "AUTO": return b
    return ORDER[max(ORDER.index(a), ORDER.index(b))]
