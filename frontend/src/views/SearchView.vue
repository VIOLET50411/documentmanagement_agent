<template>
  <div class="search-page workbench-page">
    <section class="search-shell card-glass">
      <div class="search-bar">
        <input v-model="query" class="input search-input" placeholder="输入检索关键词或问题" @keydown.enter="doSearch" />
        <select v-model="searchType" class="input search-type-select">
          <option value="hybrid">混合检索</option>
          <option value="vector">向量检索</option>
          <option value="keyword">关键词检索</option>
          <option value="graph">图谱检索</option>
        </select>
        <button class="btn btn-primary" :disabled="!query.trim() || isLoading" @click="doSearch">
          {{ isLoading ? "检索中..." : "开始检索" }}
        </button>
      </div>

      <div class="results-area">
        <p v-if="results.length" class="results-count">共找到 {{ results.length }} 条结果</p>
        <div v-for="(result, idx) in results" :key="idx" class="result-card card animate-fade-in">
          <div class="result-header">
            <span class="result-rank">#{{ idx + 1 }}</span>
            <span class="result-title">{{ result.doc_title || result.document_title || "未命名文档" }}</span>
            <span class="badge badge-primary">{{ searchTypeLabel }}</span>
            <span class="result-score">得分 {{ Number(result.score || result.rrf_score || 0).toFixed(4) }}</span>
          </div>
          <p class="result-content">{{ result.snippet || result.content || "暂无摘要内容" }}</p>
          <div class="result-meta">
            <span v-if="result.page_number">页码 {{ result.page_number }}</span>
            <span v-if="result.section_title">章节 {{ result.section_title }}</span>
            <span v-if="result.department">部门 {{ result.department }}</span>
          </div>
        </div>

        <div v-if="searched && results.length === 0" class="empty-results">
          <p>没有找到相关结果。</p>
          <p class="text-hint">可以尝试调整关键词，或切换检索模式。</p>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { searchApi } from '@/api/search'

const query = ref('')
const searchType = ref<'hybrid' | 'vector' | 'keyword' | 'graph'>('hybrid')
const results = ref<any[]>([])
const isLoading = ref(false)
const searched = ref(false)

const searchTypeLabel = computed(() => {
  const map = {
    hybrid: '混合检索',
    vector: '向量检索',
    keyword: '关键词检索',
    graph: '图谱检索',
  }
  return map[searchType.value]
})

async function doSearch() {
  if (!query.value.trim()) return
  isLoading.value = true
  searched.value = true
  try {
    const res = await searchApi.search(query.value, { search_type: searchType.value, top_k: 10 })
    results.value = res.results || []
  } catch {
    results.value = []
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
.workbench-page {
  padding: 0 12px 12px;
  overflow-y: auto;
  height: 100%;
}

.search-shell {
  max-width: 1080px;
  margin: 0 auto;
}

.search-bar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 200px auto;
  gap: var(--space-3);
  margin-bottom: var(--space-6);
}

.results-count {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-4);
}

.results-area {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.result-card {
  padding: 18px 20px;
}

.result-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}

.result-rank {
  font-weight: 700;
  color: var(--color-primary-hover);
  font-size: var(--text-sm);
}

.result-title {
  font-weight: 700;
  flex: 1;
}

.result-score {
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.result-content {
  font-size: 0.98rem;
  color: var(--text-secondary);
  line-height: 1.8;
  margin-bottom: var(--space-3);
}

.result-meta {
  display: flex;
  gap: var(--space-4);
  font-size: var(--text-xs);
  color: var(--text-tertiary);
  flex-wrap: wrap;
}

.empty-results {
  text-align: center;
  padding: var(--space-10);
  color: var(--text-secondary);
}

.text-hint {
  margin-top: var(--space-1);
  color: var(--text-tertiary);
}

@media (max-width: 900px) {
  .workbench-page {
    padding: 0 0 12px;
  }

  .search-bar {
    grid-template-columns: 1fr;
  }
}
</style>
