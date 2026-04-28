# Alembic Migration Guide

常用命令：

```bash
alembic revision --autogenerate -m "init schema"
alembic upgrade head
```

说明：

- `env.py` 已加载当前 SQLAlchemy 模型元数据。
- 数据库连接默认读取 `backend/.env` 或仓库根目录 `.env` 中的 PostgreSQL 配置。
- 生产环境应通过 CI/CD 显式执行迁移，不建议依赖自动建表。
