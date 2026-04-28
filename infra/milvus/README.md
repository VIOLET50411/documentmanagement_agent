# Milvus Notes

- 开发环境使用 `docker-compose.yml` 中的单机版 Milvus。
- 生产环境建议切换为分离式部署，并启用对象存储与监控。
- 多租户隔离设计以 `tenant_id` 作为 Partition Key，实际建表逻辑保留在向量接入阶段完成。
- AI 向量写入逻辑仍以 `TODO: [AI_API]` 标记，后续在 `backend/app/retrieval/milvus_client.py` 中接入。
