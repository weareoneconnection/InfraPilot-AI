# InfraPilot AI

**交通基础设施现场多模态自主感知与闭环处置系统**

InfraPilot AI 是面向交通基础设施施工现场的独立参赛作品。它不是项目管理大平台，而是把现场照片、语音、GPS、构件标识与文本观察转成一个可追踪的工程事件，再组织专业智能体完成风险判断、处置计划、人工授权、任务派发与复检核验。

## 一键运行

要求 Python 3.12+：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

打开 http://127.0.0.1:8101 。无需模型 API Key 也能运行完整离线黄金链路。

如需真实多模态视觉模型，在 `.env` 或环境变量配置 OpenAI-compatible endpoint：

```bash
export MODEL_BASE_URL="https://your-gateway.example/v1"
export MODEL_API_KEY="..."
export VISION_MODEL_NAME="your-vision-model"
```

## 黄金链路

`Sense → Understand → Assess → Reason → Human Gate → Act → Re-inspect → Verify → Close`

默认演示数据是**合成场景**；执行动作进入 demo queue，`external_side_effect=false`，不会对真实项目产生外部影响。

## 顶级架构设计要点

- Multimodal Perception Adapter：图片可接 OpenAI-compatible vision model；无模型时使用可复现规则路径。
- Conservative Risk Fusion：最终风险取报告人、规则/模型风险的较高值，AI 不静默降低人工风险。
- Dynamic Specialist Team：HSE、质量、施工、工程、计划、设备按现场信号动态组队。
- Evidence Contract：每条 SUPPORTED Finding 必须带来源引用。
- Human Authority：分析与执行分离，未审批不能派发行动。
- Execution Receipt：行动生成内容摘要与可审计回执。
- Re-inspection Verification：整改后必须复检，核验通过才能关闭。
- Competition Benchmark：离线风险识别与专业路由评测，可加入 CI。

## 重要边界

当前包是竞赛级可运行基础，不宣称已连接真实 CCTV、SCADA、P6、客户项目或已实现生产级 CV 准确率。正式试点需要真实脱敏图像集、模型盲测、对象存储、恶意文件扫描、SSO/RBAC 和 durable job queue。
