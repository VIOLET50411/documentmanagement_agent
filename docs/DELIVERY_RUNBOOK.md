# DocMind 交付运行手册

## 1. 目的

本手册用于在当前仓库上执行交付前最小验证，确保交付说明与真实运行状态一致。

## 2. 推荐检查顺序

1. 容器状态
2. 健康检查
3. 登录与主页面
4. 文档上传与状态推进
5. 检索与问答
6. 管理端系统状态
7. 自动化预检

## 3. 关键检查点

### 容器状态

```powershell
docker ps
```

至少确认：

- `docmind-backend`
- `docmind-frontend`
- `docmind-celery-worker`
- `docmind-postgres`
- `docmind-redis`
- `docmind-minio`
- `docmind-milvus`
- `docmind-elasticsearch`
- `docmind-neo4j`

### 健康检查

```powershell
Invoke-RestMethod http://localhost:18000/health
```

### 自动化预检

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-preflight.ps1
```

## 4. 建议验收动作

### 鉴权

- 使用 `admin_demo / Password123` 登录
- 确认当前用户接口正常

### 文档主链路

- 上传文档
- 查看列表
- 查看状态
- 查看事件
- 对失败任务执行重试

### 问答主链路

- 发起一次 SSE 问答
- 确认前端收到事件流
- 确认回答带引用或明确说明证据不足

### 管理端

- 系统后端状态
- 检索指标
- 安全事件
- 运行时指标
- 评估结果

## 5. 常见交付误判

- 健康检查通过，不等于检索质量已经足够
- 容器在跑，不等于前端能正常完成核心流程
- 有 SSE 输出，不等于回答质量已经达标
- 评估框架存在，不等于质量门禁已经成熟

## 6. 当前阶段交付判断

当前系统已经适合按“企业文档平台开发版 / 演示版 / 内部验证版”交付。

如果要按“高质量文档 Agent 成品”交付，还需要继续补强检索质量、多轮追问和结构化回答能力。
