"""Risk from text signals, fused with the reporter and vision; response and closure SLAs."""
from __future__ import annotations

from .text import matched

ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

RULES: list[tuple[str, list[str]]] = [
    ("CRITICAL", ["collapse", "collapsed", "fatal", "electrocution", "exposed live", "person fell", "worker fell",
                  "坍塌", "触电", "死亡", "人员坠落", "带电裸露", "漏电"]),
    ("HIGH", ["unprotected edge", "open edge", "work at height", "working at height", "no fall protection", "without fall protection",
              "guardrail missing", "missing guardrail", "no harness", "without harness", "mobile crane", "lifting", "suspended load",
              "deep excavation", "confined space", "hot work",
              "临边", "无防护", "高处作业", "未系安全带", "吊装", "深基坑", "受限空间", "动火"]),
    ("MEDIUM", ["crack", "cracks", "defect", "ncr", "honeycombing", "spalling", "corrosion", "spill", "leak", "blocked access",
                "access route blocked", "no helmet", "missing ppe",
                "裂缝", "缺陷", "蜂窝", "剥落", "锈蚀", "泄漏", "通道堵塞", "未戴安全帽"]),
]

# hours to first response / to verified closure
SLA_HOURS = {"CRITICAL": (1, 24), "HIGH": (4, 72), "MEDIUM": (24, 168), "LOW": (72, 336)}


def assess(text: str) -> tuple[str, list[str]]:
    for level, terms in RULES:
        hits = matched(text, terms)
        if hits:
            return level, hits
    return "LOW", []


def higher(*levels: str) -> str:
    known = [lv for lv in levels if lv in ORDER]
    return max(known, key=ORDER.index) if known else "LOW"


def stop_work(risk: str, signals: list[str]) -> bool:
    return risk == "CRITICAL" or (risk == "HIGH" and bool(signals))
