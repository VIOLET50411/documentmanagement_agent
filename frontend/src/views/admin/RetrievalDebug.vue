<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="section-header">
        <div>
          <h2>检索调试台</h2>
          <p class="page-copy">按单次查询查看改写结果，并排比较原始查询和改写后查询的命中文档，方便判断改写是否真的提升了召回质量。</p>
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

      <section v-if="result" class="inspect-panel save-panel">
        <div class="panel-mini-head">
          <h3>保存为评测样本</h3>
          <p>把当前调试结果沉淀到手工评测集。下次运行评测时，这条样本会并入自动生成的数据集。</p>
        </div>
        <div class="save-grid">
          <textarea
            v-model="expectedAnswer"
            class="input save-answer"
            rows="3"
            placeholder="填写这条问题的期望答案或标准引用片段"
          />
          <textarea
            v-model="sampleNotes"
            class="input save-notes"
            rows="3"
            placeholder="可选备注，例如：原始查询命中偏泛，改写后命中制度正文"
          />
        </div>
        <div class="save-actions">
          <button class="btn btn-primary" :disabled="savingSample || !canSaveSample" @click="saveSample">
            {{ savingSample ? "保存中..." : "保存评测样本" }}
          </button>
          <span v-if="saveMessage" class="save-message">{{ saveMessage }}</span>
        </div>
      </section>

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
              <span>原始命中</span>
              <strong>{{ result.original_total ?? 0 }}</strong>
            </div>
            <div class="summary-item">
              <span>改写后命中</span>
              <strong>{{ result.total ?? 0 }}</strong>
            </div>
          </div>
        </section>

        <div class="compare-grid">
          <section class="inspect-panel">
            <div class="panel-mini-head">
              <h3>原始查询结果</h3>
              <p>直接用用户输入进行检索，当前返回 {{ result.original_total ?? 0 }} 条。</p>
            </div>
            <div v-if="result.original_results?.length" class="result-list">
              <article
                v-for="(item, index) in result.original_results"
                :key="`original-${item.chunk_id || item.doc_id || index}`"
                class="result-card"
              >
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
            <p v-else class="empty-text">原始查询没有命中文档。</p>
          </section>

          <section class="inspect-panel">
            <div class="panel-mini-head">
              <h3>改写后查询结果</h3>
              <p>使用改写后的检索词执行同样的检索流程，当前返回 {{ result.total ?? 0 }} 条。</p>
            </div>
            <div v-if="result.results?.length" class="result-list">
              <article
                v-for="(item, index) in result.results"
                :key="`rewritten-${item.chunk_id || item.doc_id || index}`"
                class="result-card"
              >
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
            <p v-else class="empty-text">改写后查询没有命中文档。</p>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { adminApi } from "@/api/admin"

type SearchType = "hybrid" | "keyword" | "vector" | "graph"

type RetrievalRow = Record<string, any>

type RetrievalDebugResult = {
  query: string
  rewritten_query: string
  rewrite_source: string
  search_type: SearchType
  original_total: number
  original_results: RetrievalRow[]
  total: number
  results: RetrievalRow[]
}

const query = ref("这个审批怎么走？")
const searchType = ref<SearchType>("hybrid")
const topK = ref(8)
const loading = ref(false)
const error = ref("")
const result = ref<RetrievalDebugResult | null>(null)
const expectedAnswer = ref("")
const sampleNotes = ref("")
const savingSample = ref(false)
const saveMessage = ref("")

const searchTypeLabel = computed(() => {
  const labels: Record<SearchType, string> = {
    hybrid: "混合检索",
    keyword: "关键词检索",
    vector: "向量检索",
    graph: "图谱检索",
  }
  return labels[searchType.value]
})

const canSaveSample = computed(() => Boolean(result.value?.query?.trim() && expectedAnswer.value.trim()))

async function runDebug() {
  if (!query.value.trim()) return
  loading.value = true
  error.value = ""
  try {
    result.value = await adminApi.getRetrievalDebug(query.value, {
      top_k: Math.min(Math.max(topK.value || 8, 1), 20),
      search_type: searchType.value,
    })
    saveMessage.value = ""
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

async function saveSample() {
  if (!result.value || !canSaveSample.value) return
  savingSample.value = true
  saveMessage.value = ""
  try {
    const payload = {
      question: result.value.query,
      answer: expectedAnswer.value.trim(),
      reference: expectedAnswer.value.trim(),
      contexts: result.value.results.map((item) => item.snippet || item.content).filter(Boolean).slice(0, 4),
      context_doc_ids: result.value.results.map((item) => item.doc_id).filter(Boolean),
      difficulty: "manual",
      task_type: "manual_debug",
      metadata: {
        rewritten_query: result.value.rewritten_query,
        rewrite_source: result.value.rewrite_source,
        search_type: searchType.value,
        notes: sampleNotes.value.trim() || null,
        original_total: result.value.original_total,
        rewritten_total: result.value.total,
      },
    }
    await adminApi.saveEvaluationDatasetSample(payload)
    saveMessage.value = "已保存到手工评测集。"
  } catch (caught: any) {
    saveMessage.value = caught?.response?.data?.detail || "保存评测样本失败。"
  } finally {
    savingSample.value = false
  }
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
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
  gap: var(--space-4);
  margin-top: var(--space-6);
}

.compare-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-4);
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

.save-panel {
  margin-top: var(--space-6);
}

.save-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.save-answer,
.save-notes {
  min-height: 92px;
  resize: vertical;
}

.save-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 16px;
}

.save-message {
  color: var(--text-secondary);
  font-size: 13px;
}

@media (max-width: 1280px) {
  .debug-grid,
  .compare-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .save-grid,
  .debug-controls {
    flex-direction: column;
  }

  .save-grid {
    grid-template-columns: 1fr;
  }

  .debug-controls {
    align-items: stretch;
  }

  .compact-field {
    width: 100%;
  }
}
</style>
