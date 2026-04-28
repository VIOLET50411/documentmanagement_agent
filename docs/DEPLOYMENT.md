# DocMind Agent 部署说明

## 1. 本地运行基线

当前仓库已按 Windows 本地开发路径验证，推荐端口如下：

- 前端: `http://localhost:15173`
- 后端: `http://localhost:18000`
- Flower: `http://localhost:15555`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`
- Milvus: `localhost:19530`
- Elasticsearch: `localhost:9200`
- MinIO API: `localhost:9000`
- MinIO Console: `http://localhost:9001`
- Neo4j Browser: `http://localhost:7474`

演示管理员账号会在后端首次启动时自动创建：

- 用户名: `admin_demo`
- 密码: `Password123`

前置环境：

- Docker Desktop
- Python 3.11+
- Node.js 20+

## 2. 推荐启动方式

### 方式 A：全容器启动

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

### 方式 B：基础设施容器 + 应用本地

先启动基础设施：

```powershell
docker compose up -d postgres redis etcd minio milvus elasticsearch neo4j
```

再分别启动后端、Celery、前端：

```powershell
cd backend
py -3 -m pip install -r requirements.txt
py -3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```powershell
cd backend
py -3 -m celery -A celery_app worker --loglevel=info --autoscale=8,2
```

```powershell
cd frontend
npm.cmd install
npm.cmd run dev -- --host 0.0.0.0 --port 5173
```

也可以直接运行仓库脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

## 3. 环境变量

- 主配置文件：`C:\Users\32020\Desktop\documentmanagement_agent\.env`
- 分发模板：`C:\Users\32020\Desktop\documentmanagement_agent\.env.example`
- AI Key 相关字段目前保持留空，后续接入真实 AI API 时再填写

如果沿用当前 `.env`，容器映射端口如下：

- `BACKEND_PORT=18000`
- `FRONTEND_PORT=15173`
- `FLOWER_PORT=15555`

## 4. 首次启动检查清单

1. 访问 `http://localhost:18000/health`，确认返回 `healthy`
2. 打开 `http://localhost:15173`
3. 使用 `admin_demo / Password123` 登录
4. 进入“系统管理”页面，确认可看到：
   - 管线任务统计
   - 安全事件列表
   - 评估与运行时指标
5. 上传一个测试文档，在文档页确认状态会更新为：
   - `queued`
   - `parsing` / `chunking` / `indexing`
   - `ready` / `partial_failed` / `failed`

如需快速验收，可运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\verify-stack.ps1
```

## 5. 基线压测（非LLM阶段）

使用内置脚本验证并发基线：

```powershell
py -3 scripts/loadtest_baseline.py --base-url http://localhost:8000
```

默认压测配置：

- 搜索：100 请求，50 并发
- 聊天首事件：40 请求，20 并发

输出指标包含：请求数、错误数、平均延迟、P95 延迟、最大延迟。

## 6. 当前实现边界

已落地：

- FastAPI + Vue3 主流程
- JWT 登录与 RBAC 基线
- 上传、解析任务、进度查询与重试
- SSE 聊天主链路
- 安全骨架、审计事件、运行时评估指标
- 默认演示管理员初始化

尚未最终落地：

- 外部 LLM / Embedding / Reranker 真实接入
- Spark 级历史文档迁移完成度
- 金融级安全策略与 DLP 联动
- 完整数据飞轮与自动调优闭环

## 7. 生产部署方向

推荐生产形态：

- Nginx 反向代理 FastAPI 与前端静态资源
- FastAPI 多副本
- PostgreSQL 主从或托管高可用
- Redis Sentinel 或托管 Redis
- MinIO / S3 对象存储
- Milvus 集群模式
- Elasticsearch 独立节点规划
- Kubernetes 统一编排

SSE 代理层建议：

- `X-Accel-Buffering: no`
- 合理读取超时
- 关闭会破坏流式返回的缓冲
