# DocMind 项目文档索引

本文件是当前仓库的统一文档入口。桌面散落版说明不再作为权威来源，所有项目说明以本目录为准。

## 推荐阅读顺序

1. [README](../README.md)：项目定位、运行入口、当前能力概览
2. [LOCAL_SETUP.md](./LOCAL_SETUP.md)：公开仓库下载后的本机配置、脱敏要求与可选云服务接入
3. [ARCHITECTURE.md](./ARCHITECTURE.md)：系统分层、核心链路、存储和治理
4. [REQUIREMENTS_SPEC.md](./REQUIREMENTS_SPEC.md)：本期功能与非功能需求
5. [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)：当前已完成、待增强和验收基线
6. [DOCUMENT_AGENT_ROADMAP.md](./DOCUMENT_AGENT_ROADMAP.md)：把系统继续做成“好用文档 Agent”的路线
7. [API.md](./API.md)：主要接口与接口分组
8. [DEPLOYMENT.md](./DEPLOYMENT.md)：本地部署、端口、启动与验收
9. [DELIVERY_RUNBOOK.md](./DELIVERY_RUNBOOK.md)：交付预检与验收建议

## 专项文档

- [RUNTIME_V2.md](./RUNTIME_V2.md)：Runtime V2、SSE、Replay、Resume
- [SYSTEM_DESIGN_SPEC.md](./SYSTEM_DESIGN_SPEC.md)：模块划分与设计约束
- [AI_API_PLACEHOLDERS.md](./AI_API_PLACEHOLDERS.md)：尚未接入真实 AI 的边界说明
- [ENTERPRISE_LLM_TUNING.md](./ENTERPRISE_LLM_TUNING.md)：企业语料导出、训练编排、模型激活
- [CC_FRONTEND_GAP_MAP.md](./CC_FRONTEND_GAP_MAP.md)：前端与参考实现的差距记录
- [DELIVERY_ACCEPTANCE_TEMPLATE.md](./DELIVERY_ACCEPTANCE_TEMPLATE.md)：交付验收模板

## 当前原则

- 说明文档必须反映当前真实实现，不再维护“未来幻想版方案稿”
- 文档中的端口、接口、脚本、状态结论应优先与当前仓库和 Docker 运行态一致
- 涉及中文内容时统一保持 UTF-8，发现乱码必须先修复再继续改动
