# DocMind 交付运行手册（非 LLM 阶段）

## 1. 目标

交付前统一执行以下动作：

1. 启动并确认基础服务与应用可达。
2. 运行自动化预检并生成归档报告。
3. 输出最终交付结论（可上线 / 需整改）。

## 2. 一键预检命令

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-preflight.ps1
```

## 2.1 本地开源免费 LLM（Ollama）接入

默认使用 `Ollama + qwen2.5:1.5b`，避免本机资源不足导致 7B 模型拉起失败。

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d ollama
docker exec docmind-ollama ollama pull qwen2.5:1.5b
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d backend celery-worker
```

验证点：

1. `GET /api/v1/admin/system/backends` 中 `llm.available=true`。
2. `llm.model=qwen2.5:1.5b` 且 `llm.model_pulled=true`。
3. `POST /api/v1/chat/stream` 能输出 `streaming` 事件并最终 `done`。

可选参数：

- `-RunTests`：附加执行后端 `pytest -q`
- `-RunFrontendBuild`：附加执行前端 `npm.cmd run build`
- `-RunLoadtest`：附加执行轻量压测
- `-RunSmokeE2E`：附加执行全链路冒烟（登录→上传→检索→SSE）

示例：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-preflight.ps1 -RunTests -RunFrontendBuild -RunLoadtest -RunSmokeE2E
```

## 3. 报告产物

脚本会自动写入：

- `reports/delivery/preflight_YYYYMMDD_HHMMSS.md`
- `reports/delivery/preflight_YYYYMMDD_HHMMSS.json`

报告包含：

- 总检查数 / 通过数 / 得分
- `READY_CANDIDATE` / `NOT_READY` 状态
- 每个检查项明细与失败原因
- 失败时附带端口与容器状态诊断

## 4. 上线门槛建议

建议门槛：

- 预检得分 >= 85
- `backend.health`、`auth.login`、`admin.system.readiness` 必须通过
- `admin.system.retrieval_integrity` 必须通过
- 后端测试与前端构建在本次发布窗口内通过
- `admin.system.backends` 中关键后端不处于持续异常

## 5. 失败处理建议

若预检失败，优先处理顺序：

1. 可用性（health / login）
2. 数据安全（扫描 / 审计 / 权限）
3. 检索稳定性（ES / Milvus / Graph）
4. 性能与体验（SSE 首事件、并发）

修复后重新执行预检并归档新报告，不覆盖旧报告。
