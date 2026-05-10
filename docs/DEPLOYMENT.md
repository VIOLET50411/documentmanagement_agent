# DocMind Agent 部署说明

## 1. 当前推荐运行方式

当前仓库默认按 Docker Compose 本地开发栈运行，推荐直接使用：

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

## 2. 当前端口

以当前运行中的容器映射为准：

- 前端：`http://localhost:15173`
- 后端：`http://localhost:18000`
- Flower：`http://localhost:15555`
- PostgreSQL：`localhost:5432`
- Redis：`localhost:6379`
- Milvus：`localhost:19530`
- Elasticsearch：`localhost:9200`
- MinIO：`localhost:9000`
- MinIO Console：`http://localhost:9001`
- Neo4j Browser：`http://localhost:7474`
- Ollama：`http://localhost:11434`
- Guardrails sidecar：`http://localhost:8090`
- Ragas sidecar：`http://localhost:8091`

## 3. 当前容器

主要服务包括：

- `docmind-backend`
- `docmind-frontend`
- `docmind-celery-worker`
- `docmind-flower`
- `docmind-postgres`
- `docmind-redis`
- `docmind-minio`
- `docmind-milvus`
- `docmind-elasticsearch`
- `docmind-neo4j`
- `docmind-ollama`
- `docmind-clamav`
- `docmind-guardrails-sidecar`
- `docmind-ragas-sidecar`

## 4. 环境准备

- Docker Desktop
- Python 3.11+
- Node.js 20+

建议补充：

- Git
- 可联网拉取 Docker 镜像和 Ollama 模型
- 建议内存 16 GB 及以上
- 建议磁盘预留 20 GB 以上

如果需要 Android / Firebase 联调，请同时参考 [LOCAL_SETUP.md](./LOCAL_SETUP.md) 中的移动端配置说明。
如果你要构建 Android App，建议直接使用 JDK 17；当前 Android Gradle Plugin 为 `8.2.1`，Java 8 环境会导致 Gradle 依赖解析失败。

初始化环境变量：

```powershell
Copy-Item .env.example .env
```

建议首次复制后立即替换本地 secret 和默认密码，不要长期保留模板值。

## 5. 首次启动建议

1. 启动 Compose 栈
2. 访问 `http://localhost:18000/health`
3. 打开 `http://localhost:15173`
4. 使用演示管理员登录：
   - 用户名：`admin_demo`
   - 密码：`Password123`
5. 上传一份测试文档，确认状态推进到 `ready` 或可解释的失败态

说明：

- 未配置 Firebase 时，Web / Docker 主链路仍可正常启动
- Android 推送、小程序推送等能力需要你自己的云端配置

## 6. Ollama 模型准备

```powershell
docker exec docmind-ollama ollama pull qwen2.5:1.5b
docker exec docmind-ollama ollama pull nomic-embed-text
```

## 7. 常用命令

查看容器：

```powershell
docker ps
```

查看后端日志：

```powershell
docker logs docmind-backend --tail 200
```

重启后端：

```powershell
docker restart docmind-backend
```

## 8. 本地代码与 Docker 同步说明

当前 `docker-compose.dev.yml` 已把本地目录挂载进容器：

- `./backend -> /app`
- `./datasets -> /workspace/datasets`
- `./reports -> /workspace/reports`

因此后端代码改动会直接影响容器内运行路径。涉及运行逻辑修改时，应在 Docker 中做最小验证后再视为完成。
