# DocMind 文档 Agent 改造路线图

## 目标

把当前 DocMind 从“能跑的企业文档问答系统”提升为“好用的文档 Agent”。

本路线图刻意不把目标定义成通用代理，而是收敛到文档场景下最重要的 5 个能力：

1. 稳定命中文档证据
2. 给出结构化结论而不是泛泛生成
3. 支持多轮追问与指代消解
4. 对无证据、低置信度、版本冲突场景做清晰治理
5. 用真实评测和运行态指标持续证明质量

## 当前判断

### 已具备的基础

- Runtime V2 已是主链路，具备任务状态、SSE、Replay、Checkpoint、Resume。
- LangGraph 执行链已落地，`intent_router -> query_rewriter -> retriever/... -> critic` 可跑通。
- 检索层已具备 ES / Milvus / Neo4j / reranker / observability。
- 前端聊天页、运行时事件流、历史会话基本可用。
- Docker 运行栈完整，后端、前端、Ollama、ES、Milvus、Neo4j、Redis、Postgres 均可联动验证。

### 当前短板

- 核心中文提示词、规则关键词、前端聊天页仍存在编码污染，直接影响中文意图识别与用户观感。
- `retriever` 仍然偏薄，只是调用统一 `HybridSearcher.search()`，缺少按任务类型做检索策略分化。
- `intent_router` 和 `query_rewriter` 仍偏规则化，面对模糊问题、追问、版本歧义时不够稳。
- 回答结构尚未强收敛到“结论 / 依据 / 引用 / 不确定点 / 下一步”，所以体感偏笨。
- 评估体系更偏“链路存活证明”，还不是“文档问答质量门禁”。

## 不做什么

- 不优先把它做成 Manus / Claude Code 这一类通用执行代理。
- 不把近期重点放在 UI 美化。
- 不把主要精力放在继续堆新工具种类。
- 不把“换更大模型”当成第一顺位解法。

## 设计原则

1. 检索优先于生成
2. 多轮上下文优先于单轮华丽措辞
3. 证据充分优先于回答流畅
4. 中文质量和 UTF-8 一票否决
5. 所有关键改造都要有 live 验证和 Docker 同步验证

## 分阶段计划

### P0：修硬伤，恢复中文与回归一致性

目标：先把会直接拉低能力上限的缺陷清掉。

涉及文件：

- `backend/app/agent/nodes/intent_router.py`
- `backend/app/agent/nodes/query_rewriter.py`
- `backend/app/agent/supervisor.py`
- `frontend/src/views/ChatView.vue`
- `backend/app/api/v1/chat.py`
- `backend/tests/integration/test_api_routes.py`

动作：

1. 彻底修复用户可见中文乱码、关键词乱码、prompt 乱码。
2. 统一聊天安全拦截文案，消除当前集成测试不一致。
3. 对 `ChatView.vue` 做 UTF-8 清理，修正文案、快捷提问、placeholder。
4. 扫描仓库典型乱码特征，避免继续扩散。

验收：

- `backend/tests/test_query_rewriter.py`
- `backend/tests/test_runtime_v2.py`
- `backend/tests/integration/test_api_routes.py`
- `frontend/npm.cmd run build`
- 最小 live chat 验证

### P1：让它先“会找”，再谈“会答”

目标：把检索从统一混合搜索，提升到按文档任务类型分化。

涉及文件：

- `backend/app/agent/nodes/retriever.py`
- `backend/app/retrieval/hybrid_searcher.py`
- `backend/app/retrieval/reranker.py`
- `backend/app/retrieval/graph_searcher.py`
- `backend/app/services/retrieval_integrity_service.py`
- `backend/app/services/retrieval_observability_service.py`

动作：

1. 在 `retriever.py` 引入任务感知检索参数，而不是只透传 `search_type`。
2. 为 `qa / summarize / compare / graph_query / statistics` 建立不同召回组合与 `top_k`。
3. 给 rerank 增加文档版本、制度名称、部门、章节权重。
4. 对“无证据”与“弱证据”做显式分档，而不是一律进入生成。
5. 将检索评估从 health 扩展到任务型指标：命中率、空结果率、重复引用率、同文档聚合率。

验收：

- 为每类意图补 focused pytest
- 新增 30-50 条真实文档问答样本
- live 查询验证至少覆盖：制度问答、制度对比、文档摘要、关系查询

### P2：把回答从“模型输出”变成“文档结论”

目标：统一答案结构，让输出适合企业文档使用。

涉及文件：

- `backend/app/agent/nodes/generator.py`
- `backend/app/agent/agents/compliance_agent.py`
- `backend/app/agent/agents/summary_agent.py`
- `backend/app/agent/agents/graph_agent.py`
- `backend/app/agent/agents/data_agent.py`
- `backend/app/agent/agents/critic_agent.py`

动作：

1. 按任务类型建立固定回答骨架：
   - 制度问答：结论 / 依据 / 引用
   - 摘要：主题 / 要点 / 风险 / 待确认项
   - 对比：相同点 / 差异点 / 影响
   - 关系：关系结论 / 证据链 / 来源
   - 统计：统计口径 / 数值 / 来源
2. `critic_agent` 不只判断“是否通过”，还要判断：
   - 是否回答了用户问题
   - 是否有足够引用
   - 是否混淆了不同文档或不同版本
   - 是否应该先澄清再回答
3. 强化“证据不足”时的标准回复，不允许空泛发挥。

验收：

- 每类 agent 至少一组结构化输出测试
- 引用去重和引用完整性测试
- live 抽样检查回答可读性和可追溯性

### P3：把多轮追问做顺

目标：让它在文档会话里不像失忆。

涉及文件：

- `backend/app/agent/nodes/query_rewriter.py`
- `backend/app/agent/runtime/langgraph_runner.py`
- `backend/app/api/v1/chat.py`
- `backend/app/api/v1/ws_chat.py`
- `backend/app/memory/session_memory.py`
- `backend/app/memory/working_memory.py`
- `frontend/src/stores/chat.ts`

动作：

1. 把当前会话中的“当前文档、当前制度、当前版本、当前部门”变成可显式利用的上下文。
2. 做指代消解：这个、那个、上文、前一个版本、刚才那份制度。
3. 做歧义澄清：当命中多个制度或多个版本时先问用户选哪个。
4. 在前端显示“本轮基于哪些文档理解上下文”，减少黑箱感。
5. 对 resume/replay 路径保持同样的上下文恢复语义。

验收：

- `test_query_rewriter.py` 增加追问场景
- `test_chat_resume.py` 和 `test_runtime_v2.py` 增加上下文恢复场景
- live 连续三轮问答验证

### P4：建立真正有用的文档 Agent 评测

目标：从“链路通了”升级到“质量够用”。

涉及文件：

- `backend/app/evaluation/golden_dataset.py`
- `backend/app/evaluation/ragas_runner.py`
- `backend/app/services/evaluation_service.py`
- `backend/app/services/runtime_evaluation_service.py`
- `reports/`

动作：

1. 建立按任务分桶的评测集：
   - 制度问答
   - 摘要
   - 对比
   - 关系
   - 统计
2. 区分两个问题：
   - 链路是否活着
   - 回答质量是否够用
3. 增加更贴近文档场景的指标：
   - 结论命中
   - 证据覆盖
   - 引用准确率
   - 版本混淆率
   - 澄清触发准确率
4. 后续把这些指标接到管理台和 CI gate。

验收：

- 新评测样本可重复运行
- 每次核心改动后能出可比较报告
- 不通过时能定位是 rewrite、retrieval、generation 还是 citation 环节

### P5：前端做成真正“好用”的文档工作台

目标：让用户能理解 agent 在做什么，并能高效迭代提问。

涉及文件：

- `frontend/src/views/ChatView.vue`
- `frontend/src/components/chat/*`
- `frontend/src/stores/chat.ts`
- `frontend/src/api/chat.ts`

动作：

1. 清理当前聊天页乱码与中英混杂。
2. 在消息层区分：
   - 结论
   - 依据
   - 引用
   - 风险/不确定性
3. 让 runtime event 更面向用户，而不是只面向研发排障。
4. 为“继续追问”“只看依据”“切换文档范围”“重新检索”提供明确入口。
5. 当证据不足时，引导用户上传文档、缩小范围、指定制度名，而不是只报空。

验收：

- 聊天页中文可读性恢复
- 核心追问流程可闭环
- Docker 前端同步后实机验证

## 推荐实施顺序

1. P0 编码与回归修复
2. P1 检索策略分化
3. P2 结构化回答
4. P3 多轮上下文
5. P4 评测收口
6. P5 前端体感收口

## 近两轮最值得先做的具体工作

### 第一轮

- 修 `intent_router.py`
- 修 `query_rewriter.py`
- 修 `ChatView.vue`
- 修 `chat.py` 当前安全拦截文案回归
- 跑 host + Docker focused tests

### 第二轮

- 重构 `retriever.py` 为任务感知检索入口
- 在 `hybrid_searcher.py` 引入 per-intent 检索配置
- 为 30-50 条真实样本建立任务型基线

## 完成标准

当以下条件都成立，才可称为“好用的文档 Agent”初版达标：

- 中文文案、提示词、规则词无明显编码污染
- 对常见制度问答能稳定命中文档证据
- 回答稳定附带结构化依据与引用
- 多轮追问不频繁丢上下文
- 无证据场景不胡答
- 关键质量指标有可重复评测
- host 与 Docker 路径都完成验证
