# DocMind Runtime V2 说明

## 1. 定位

Runtime V2 是当前 DocMind 的主运行链路，用于承载文档问答过程中的状态流、工具调用、回放和恢复能力。

## 2. 当前能力

- 统一 Runtime 请求结构
- SSE 事件输出
- 运行时任务存储
- Replay
- Checkpoint
- Resume
- 工具调用决策记录
- 性能与回退指标

## 3. 典型链路

1. 接收聊天请求
2. 注入用户、租户和上下文
3. 执行查询改写、检索、专项 agent、审查
4. 以 SSE 持续输出事件
5. 记录 trace、消息、决策和指标

## 4. 相关接口

- `POST /api/v1/chat/stream`
- `POST /api/v1/chat/message`
- `GET /api/v1/admin/runtime/tasks`
- `GET /api/v1/admin/runtime/metrics`
- `GET /api/v1/admin/runtime/tool-decisions`
- `GET /api/v1/admin/runtime/tool-decisions/summary`
- `POST /api/v1/admin/runtime/replay`

## 5. 当前价值

Runtime V2 的意义在于，DocMind 已经不是只会返回一段字符串的聊天后端，而是具备可追踪、可回放、可治理的问答运行内核。
