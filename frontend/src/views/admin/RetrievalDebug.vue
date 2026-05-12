<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="section-header">
        <div>
          <h2>检索调试台</h2>
          <p class="page-copy">按单次查询查看改写结果、检索模式和命中文档，适合排查“为什么没命中”和“为什么引用了这几篇”。</p>
        </div>
      </div>

      <div class="debug-toolbar">
        <textarea
          v-model="query"
          class="input debug-query"
          rows="3"
          placeholder="输入一个真实问题，例如：这个审批怎么走？"
        />
        <div class="debug-controls">
          <select v-model="searchType" class="input compact-field">
            <option value="hybrid">混合检索</option>
            <option value="keyword">关键词检索</option>
            <option value="vector">向量检索</option>
            <option value="graph">图谱检索</option>
          </select>
          <input v-model.number="topK" class="input compact-field" type="number" min="1" max="20" />
          <button class="btn btn-primary" :disabled="loading || !query.trim()" @click="runDebug">
            {{ loading ? "调试中..." : "开始调试" }}
          </button>
        </div>
      </div>

      <div v-if="error" class="error-banner">{{ error }}</div>

      <div v-if="result" class="debug-grid">
        <section class="inspect-panel summary-panel">
          <div class="panel-mini-head">
            <h3>查询链路</h3>
          </div>
          <div class="summary-list">
            <div class="summary-item">
              <span>原始查询</span>
              <strong>{{ result.query || "-" }}</strong>
            </div>
            <div class="summary-item">
              <span>改写后查询</span>
              <strong>{{ result.rewritten_query || "-" }}</strong>
            </div>
            <div class="summary-item">
              <span>改写来源</span>
              <strong>{{ result.rewrite_source || "passthrough" }}</strong>
            </div>
            <div class="summary-item">
              <span>检索模式</span>
              <strong>{{ searchTypeLabel }}</strong>
            </div>
            <div class="summary-item">
              <span>命中数量</span>
              <strong>{{ result.total ?? 0 }}</strong>
            </div>
          </div>
        </section>

        <section class="inspect-panel">
          <div class="panel-mini-head">
            <h3>命中文档</h3>
            <p>按当前检索策略返回的前 {{ result.total ?? 0 }} 条结果。</p>
          </div>

          <div v-if="result.results?.length" class="result-list">
            <article v-for="(item, index) in result.results" :key="item.chunk_id || item.doc_id || index" class="result-card">
              <div class="result-head">
                <div class="result-title-wrap">
                  <span class="result-rank">#{{ index + 1 }}</span>
                  <strong class="result-title">{{ item.document_title || item.doc_title || "未命名文档" }}</strong>
                </div>
                <div class="result-badges">
                  <span class="badge badge-primary">{{ item.source_type || searchType }}</span>
                  <span class="badge badge-secondary">score {{ formatScore(item.score ?? item.rrf_score) }}</span>
                </div>
              </div>
              <p class="result-snippet">{{ item.snippet || item.content || "暂无摘要内容" }}</p>
              <div class="result-meta">
                <span v-if="item.section_title">章节：{{ item.section_title }}</span>
                <span v-if="item.page_number">页码：{{ item.page_number }}</span>
                <span v-if="item.department">部门：{{ item.department }}</span>
                <span v-if="item.doc_id">文档 ID：{{ item.doc_id }}</span>
              </div>
            </article>
          </div>

          <p v-else class="empty-text">当前查询没有命中文档。</p>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { adminApi } from "@/api/admin"

type SearchType = "hybrid" | "keyword" | "vector" | "graph"

type RetrievalDebugResult = {
  query: string
  rewritten_query: string
  rewrite_source: string
  search_type: SearchType
  total: number
  results: Array<Record<string, any>>
}

const query = ref("这个审批怎么走？")
const searchType = ref<SearchType>("hybrid")
const topK = ref(8)
const loading = ref(false)
const error = ref("")
const result = ref<RetrievalDebugResult | null>(null)

const searchTypeLabel = computed(() => {
  const labels: Record<SearchType, string> = {
    hybrid: "混合检索",
    keyword: "关键词检索",
    vector: "向量检索",
    graph: "图谱检索",
  }
  return labels[searchType.value]
})

async function runDebug() {
  if (!query.value.trim()) return
  loading.value = true
  error.value = ""
  try {
    result.value = await adminApi.getRetrievalDebug(query.value, {
      top_k: Math.min(Math.max(topK.value || 8, 1), 20),
      search_type: searchType.value,
    })
  } catch (caught: any) {
    result.value = null
    error.value = caught?.response?.data?.detail || "加载检索调试结果失败。"
  } finally {
    loading.value = false
  }
}

function formatScore(value?: number | null) {
  return Number(value || 0).toFixed(4)
}
</script>

<style scoped>
.page-copy {
  margin-top: 8px;
  color: var(--text-secondary);
}

.debug-toolbar {
  display: grid;
  gap: 16px;
  margin-top: var(--space-5);
}

.debug-query {
  min-height: 92px;
  resize: vertical;
}

.debug-controls {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.compact-field {
  width: 160px;
}

.debug-grid {
  display: grid;
  grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
  gap: var(--space-4);
  margin-top: var(--space-6);
}

.inspect-panel {
  border: 1px solid var(--border-color);
  border-radius: 24px;
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent);
  padding: var(--space-5);
}

.panel-mini-head h3 {
  margin-bottom: 6px;
}

.panel-mini-head p,
.result-snippet,
.result-meta {
  color: var(--text-secondary);
}

.summary-list {
  display: grid;
  gap: 14px;
  margin-top: 16px;
}

.summary-item {
  display: grid;
  gap: 4px;
}

.summary-item span {
  font-size: 12px;
  color: var(--text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.summary-item strong {
  line-height: 1.6;
  word-break: break-word;
}

.result-list {
  display: grid;
  gap: 12px;
  margin-top: 16px;
}

.result-card {
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.34);
  border: 1px solid var(--border-color-subtle);
}

.result-head,
.result-title-wrap,
.result-badges,
.result-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.result-head {
  justify-content: space-between;
}

.result-rank {
  color: var(--color-primary-hover);
  font-weight: 700;
}

.result-title {
  line-height: 1.5;
}

.result-snippet {
  margin-top: 10px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}

.result-meta {
  margin-top: 10px;
  font-size: 12px;
}

.error-banner {
  margin-top: var(--space-4);
  padding: 14px 16px;
  border-radius: 16px;
  border: 1px solid rgba(198, 40, 40, 0.18);
  background: rgba(198, 40, 40, 0.08);
  color: #b3261e;
}

@media (max-width: 1100px) {
  .debug-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .debug-controls {
    flex-direction: column;
    align-items: stretch;
  }

  .compact-field {
    width: 100%;
  }
}
</style>
