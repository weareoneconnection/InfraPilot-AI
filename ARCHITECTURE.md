# Architecture

```text
 Field console (mobile-first) · REST API
                 │
            FieldPilot service
 ┌───────────┬────────────┬────────────┬──────────────┬─────────────┐
 Perception   Location     Risk & SLA   Evidence-routed  Re-inspection
 (signature,  (asset id,   (text rules, specialists      verifier
  SHA-256,     QR, GPS,     vision,      (BM25 packs,    (7 checks)
  dHash,       photo EXIF,  never lower) cited findings)
  EXIF, vision) geofence)
 └───────────┴────────────┴────────────┴──────────────┴─────────────┘
                 │
  SQLite: media · events · findings · tasks · receipts · audit   +  asset registry (JSON)
```

| Module | Responsibility |
| --- | --- |
| `perception.py` | File signatures, row+column dHash, EXIF time/offset/GPS, haversine distance, validated vision |
| `risk.py` | Bilingual word-boundary risk rules, fusion, stop-work, SLA hours |
| `service.py` | Report, locate, route, analyse, approve, dispatch, tasks, re-inspect, close, precedents, dashboard |
| `knowledge.py` / `text.py` | Governed knowledge packs with BM25 (Latin words + CJK bigrams) |
| `synthetic.py` | Generated before/after site photos with EXIF for demos and the benchmark |
| `main.py` | REST API and console |

Production evolution: object storage for media, a durable offline queue in the mobile client, signed capture (device attestation), enterprise identity for approvers and inspectors, notifications to the responsible roles, connectors to the project's NCR/HSE systems.
