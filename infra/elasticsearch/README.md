# Elasticsearch Notes

- 开发环境使用单节点 Elasticsearch 8。
- 中文分词推荐生产环境安装 `analysis-ik` 插件，并为文档索引单独定义中文 analyzer。
- 当前仓库保留 BM25 检索骨架，真实索引模板与混合检索权重在 AI 检索接入阶段完成。
