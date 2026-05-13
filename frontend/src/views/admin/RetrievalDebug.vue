<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <div class="section-header">
        <div>
          <h2>检索排查</h2>
          <p class="page-copy">输入一个真实问题，查看系统在改写前后分别找到了哪些资料，便于判断“问题理解”是否帮助了检索结果。</p>
        </div>
      </div>

      <div class="debug-toolbar">
        <textarea v-model="query" class="input debug-query" rows="3" placeholder="例如：这个审批要怎么走？" />
        <div class="debug-controls">
          <select v-model="searchType" class="input compact-field">
            <option value="hybrid">综合检索</option>
            <option value="keyword">关键词检索</option>
            <option value="vector">语义检索</option>
            <option value="graph">关系检索</option>
          </select>
          <input v-model.number="topK" class="input compact-field" type="number" min="1" max="20" />
          <button class="btn btn-primary" :disabled="loading || !query.trim()" @click="runDebug">
            {{ loading ? "排查中..." : "开始排查" }}
          </button>
        </div>
      </div>

      <StatusMessage v-if="error" tone="error" :message="error" />

      <section v-if="result" class="inspect-panel save-panel">
        <div class="panel-mini-head">
          <h3>保存成手工样本</h3>
          <p>把当前这次排查结果加入手工检查集。下次跑问答效果检查时，会把这条样本一起带上。</p>
        </div>
        <div class="save-grid">
          <textarea v-model="expectedAnswer" class="input save-answer" rows="3" placeholder="写下你期望系统回答的内容，或贴一段标准答案" />
          <textarea v-model="sampleNotes" class="input save-notes" rows="3" placeholder="可选备注，例如：原问题容易跑偏，改写后更容易命中制度文档" />
        </div>
        <div class="save-actions">
          <button class="btn btn-primary" :disabled="savingSample || !canSaveSample" @click="saveSample">
            {{ savingSample ? "保存中..." : "保存样本" }}
          </button>
          <span v-if="saveMessage" class="save-message">{{ saveMessage }}</span>
        </div>
      </section>

      <div v-if="result" class="debug-grid">
        <section class="inspect-panel summary-panel">
          <div class="panel-mini-head">
            <h3>这次系统怎么理解问题</h3>
          </div>
          <div class="summary-list">
            <div class="summary-item"><span>原问题</span><strong>{{ result.query || "-" }}</strong></div>
            <div class="summary-item"><span>系统改写后</span><strong>{{ result.rewritten_query || "-" }}</strong></div>
            <div class="summary-item"><span>改写来源</span><strong>{{ readableRewriteSource(result.rewrite_source) }}</strong></div>
            <div class="summary-item"><span>检索方式</span><strong>{{ searchTypeLabel }}</strong></div>
            <div class="summary-item"><span>改写前找到</span><strong>{{ result.original_total ?? 0 }}</strong></div>
            <div class="summary-item"><span>改写后找到</span><strong>{{ result.total ?? 0 }}</strong></div>
          </div>
        </section>

        <div class="compare-grid">
          <section class="inspect-panel">
            <div class="panel-mini-head">
              <h3>直接按原问题去找</h3>
              <p>不做额外处理，直接拿用户输入去检索。</p>
            </div>
            <div v-if="result.original_results?.length" class="result-list">
              <article v-for="(item, index) in result.original_results" :key="`original-${item.chunk_id || item.doc_id || index}`" class="result-card">
                <div class="result-head">
                  <div class="result-title-wrap">
                    <span class="result-rank">#{{ index + 1 }}</span>
                    <strong class="result-title">{{ item.document_title || item.doc_title || "未命名资料" }}</strong>
                  </div>
                  <div class="result-badges">
                    <span class="badge badge-primary">{{ searchTypeLabel }}</span>
                    <span class="badge badge-secondary">{{ scoreLabel(item) }}</span>
                  </div>
                </div>
                <p class="result-snippet">{{ item.snippet || item.content || "暂时没有摘要内容" }}</p>
                <div class="result-meta">
                  <span v-if="item.section_title">章节：{{ item.section_title }}</span>
                  <span v-if="item.page_number">页码：{{ item.page_number }}</span>
                  <span v-if="item.department">部门：{{ item.department }}</span>
                  <span v-if="item.doc_id">文档 ID：{{ item.doc_id }}</span>
                </div>
              </article>
            </div>
            <EmptyState v-else title="按原问题没有找到资料。" description="这通常说明问题太短，或者资料里没有明显对应内容。" />
          </section>

          <section class="inspect-panel">
            <div class="panel-mini-head">
              <h3>按系统理解后的问题去找</h3>
              <p>先把问题改写得更完整，再按同样方式去检索。</p>
            </div>
            <div v-if="result.results?.length" class="result-list">
              <article v-for="(item, index) in result.results" :key="`rewritten-${item.chunk_id || item.doc_id || index}`" class="result-card">
                <div class="result-head">
                  <div class="result-title-wrap">
                    <span class="result-rank">#{{ index + 1 }}</span>
                    <strong class="result-title">{{ item.document_title || item.doc_title || "未命名资料" }}</strong>
                  </div>
                  <div class="result-badges">
                    <span class="badge badge-primary">{{ searchTypeLabel }}</span>
                    <span class="badge badge-secondary">{{ scoreLabel(item) }}</span>
                  </div>
                </div>
                <p class="result-snippet">{{ item.snippet || item.content || "暂时没有摘要内容" }}</p>
                <div class="result-meta">
                  <span v-if="item.section_title">章节：{{ item.section_title }}</span>
                  <span v-if="item.page_number">页码：{{ item.page_number }}</span>
                  <span v-if="item.department">部门：{{ item.department }}</span>
                  <span v-if="item.doc_id">文档 ID：{{ item.doc_id }}</span>
                </div>
              </article>
            </div>
            <EmptyState v-else title="按改写后的问题也没有找到资料。" description="可以试着补充更具体的制度名、流程名或部门名。" />
          </section>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue"
import { adminApi } from "@/api/admin"
import EmptyState from "@/components/common/EmptyState.vue"
import StatusMessage from "@/components/common/StatusMessage.vue"
import { getApiErrorMessage } from "@/utils/adminUi"

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

const query = ref("这个审批要怎么走？")
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
    hybrid: "综合检索",
    keyword: "关键词检索",
    vector: "语义检索",
    graph: "关系检索",
  }
  return labels[searchType.value]
})

const canSaveSample = computed(() => Boolean(result.value?.query?.trim() && expectedAnswer.value.trim()))

function readableRewriteSource(source: string) {
  const map: Record<string, string> = {
    passthrough: "没有改写，直接使用原问题",
    llm: "系统补全了问题表达",
    rule: "系统按规则做了改写",
  }
  return map[source] || source || "未知"
}

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
    error.value = getApiErrorMessage(caught, "检索结果暂时没有加载出来，请稍后再试。")
  } finally {
    loading.value = false
  }
}

function formatScore(value?: number | null) {
  return Number(value || 0).toFixed(4)
}

function scoreLabel(item: Record<string, any>) {
  if (item.rrf_score !== undefined && item.rrf_score !== null) {
    return `综合得分 ${formatScore(item.rrf_score)}`
  }
  return `相关度 ${formatScore(item.score)}`
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
        source: "retrieval_debug",
        rewritten_query: result.value.rewritten_query,
        rewrite_source: result.value.rewrite_source,
        search_type: searchType.value,
        notes: sampleNotes.value.trim() || null,
        original_total: result.value.original_total,
        rewritten_total: result.value.total,
      },
    }
    await adminApi.saveEvaluationDatasetSample(payload)
    saveMessage.value = "样本已经保存，下次检查时会一起带上。"
  } catch (caught: any) {
    saveMessage.value = getApiErrorMessage(caught, "样本保存失败，请稍后再试。")
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
  margin-top: 16px;
  flex-wrap: wrap;
}

.save-message {
  color: var(--text-secondary);
}

@media (max-width: 1100px) {
  .debug-grid,
  .compare-grid,
  .save-grid {
    grid-template-columns: 1fr;
  }
}
</style>
