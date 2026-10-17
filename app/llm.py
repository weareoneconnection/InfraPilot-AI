from __future__ import annotations
import base64, json, os
import httpx

BASE = os.getenv("MODEL_BASE_URL", "").rstrip("/")
KEY = os.getenv("MODEL_API_KEY", "")
MODEL = os.getenv("MODEL_NAME", "gpt-4.1-mini")
VISION = os.getenv("VISION_MODEL_NAME", MODEL)
TIMEOUT = float(os.getenv("MODEL_TIMEOUT_S", "60"))


def configured() -> bool:
    return bool(BASE and KEY)

async def json_chat(system: str, user: str, model: str | None = None) -> dict | None:
    if not configured():
        return None
    payload = {
        "model": model or MODEL,
        "messages": [{"role":"system","content":system},{"role":"user","content":user}],
        "response_format": {"type":"json_object"},
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(f"{BASE}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            return json.loads(text)
    except Exception:
        return None

async def vision_assess(content: bytes, media_type: str, description: str) -> dict | None:
    if not configured() or not media_type.startswith("image/"):
        return None
    uri = f"data:{media_type};base64,{base64.b64encode(content).decode()}"
    payload = {
        "model": VISION,
        "messages": [
            {"role":"system","content":"You are a transport-infrastructure field inspection vision model. Return JSON only with hazards(array), objects(array), risk(LOW|MEDIUM|HIGH|CRITICAL), confidence(0..1), uncertainty(array). Do not claim a fact you cannot see."},
            {"role":"user","content":[{"type":"text","text":description},{"type":"image_url","image_url":{"url":uri}}]},
        ],
        "response_format":{"type":"json_object"},
        "temperature":0,
    }
    headers={"Authorization":f"Bearer {KEY}","Content-Type":"application/json"}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r=await client.post(f"{BASE}/chat/completions",headers=headers,json=payload)
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None
