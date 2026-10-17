# Architecture

```text
Field PWA / API
      │
      ▼
Perception Adapter ── Photo / Voice / Text / GPS / QR / IoT
      │
      ▼
Event Fusion → Risk Engine → Context Resolver
      │
      ▼
Dynamic Specialist Team
 HSE / Quality / Construction / Engineering / Planning / Plant
      │
      ▼
Evidence-backed Findings → Decision Plan
      │
      ▼
Human Approval Gate
      │
      ▼
Action Dispatcher → Execution Receipt
      │
      ▼
Re-inspection → Verification Receipt → Close
```

Production evolution: object storage + queue/outbox + independent verifier + real vision benchmark + enterprise identity.
