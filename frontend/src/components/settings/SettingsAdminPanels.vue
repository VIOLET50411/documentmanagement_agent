<template>
  <div class="content-block">
    <div class="block-head">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ summary }}</p>
      </div>
      <button v-if="isAdmin" class="btn btn-ghost btn-sm" @click="loadAdminDiagnostics" :disabled="loadingAdminDiagnostics">
        {{ loadingAdminDiagnostics ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <section v-if="!isAdmin" class="settings-panel">
      <p class="empty-text">该部分仅管理员可查看。</p>
    </section>

    <template v-else>
      <section v-if="section === 'models'" class="settings-panel">
        <h3>企业模型路由</h3>
        <div class="status-grid two-col">
          <div class="status-card">
            <span>企业模型开关</span>
            <strong>{{ llmDomainConfig?.enterprise_enabled ? '已开启' : '未开启' }}</strong>
            <small>控制制度、审批、预算等领域问题是否走企业策略。</small>
          </div>
          <div class="status-card">
            <span>企业模型名</span>
            <strong>{{ llmDomainConfig?.enterprise_model_name || '-' }}</strong>
            <small>当前企业文档场景使用的主模型。</small>
          </div>
          <div class="status-card">
            <span>灰度比例</span>
            <strong>{{ llmDomainConfig?.enterprise_canary_percent ?? 0 }}%</strong>
            <small>企业策略模型当前对租户放量比例。</small>
          </div>
          <div class="status-card">
            <span>最小语料字符数</span>
            <strong>{{ llmDomainConfig?.enterprise_corpus_min_chars ?? '-' }}</strong>
            <small>达到该阈值后才适合企业文档专用策略。</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'models'" class="settings-panel">
        <h3>检索完整性</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>健康状态</span>
            <strong>{{ retrievalIntegrity?.healthy ? '健康' : '待校准' }}</strong>
            <small>按抽样回查评估当前检索链路是否可用于高置信回答。</small>
          </div>
          <div class="status-card">
            <span>完整性评分</span>
            <strong>{{ retrievalIntegrity?.score ?? '-' }}</strong>
            <small>聚合 ES / Milvus / Graph 的完整性检查结果。</small>
          </div>
          <div class="status-card">
            <span>Milvus 召回率</span>
            <strong>{{ formatPercent(retrievalIntegrity?.stats?.milvus_sample_recall) }}</strong>
            <small>向量检索抽样召回表现。</small>
          </div>
        </div>
        <ul v-if="retrievalIntegrity?.blockers?.length" class="compact-list">
          <li v-for="item in retrievalIntegrity.blockers" :key="item.id">
            <strong>{{ item.id }}</strong>
            <span>{{ item.message }}</span>
          </li>
        </ul>
      </section>

      <section v-if="section === 'runtime'" class="settings-panel">
        <h3>Runtime 指标</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>TTFT P95</span>
            <strong>{{ runtimeMetrics?.summary?.ttft_ms_p95 ?? '-' }} ms</strong>
            <small>首字节时间，反映响应起始速度。</small>
          </div>
          <div class="status-card">
            <span>完成耗时 P95</span>
            <strong>{{ runtimeMetrics?.summary?.completion_ms_p95 ?? '-' }} ms</strong>
            <small>整轮回答结束耗时。</small>
          </div>
          <div class="status-card">
            <span>SSE 断连数</span>
            <strong>{{ runtimeMetrics?.summary?.sse_disconnects ?? 0 }}</strong>
            <small>最近采样窗口内的断连累计。</small>
          </div>
          <div class="status-card">
            <span>回退率</span>
            <strong>{{ formatPercent(runtimeMetrics?.summary?.fallback_rate) }}</strong>
            <small>说明真实链路触发降级的比例。</small>
          </div>
          <div class="status-card">
            <span>拒绝率</span>
            <strong>{{ formatPercent(runtimeMetrics?.summary?.deny_rate) }}</strong>
            <small>工具权限网关拒绝调用的比例。</small>
          </div>
          <div class="status-card">
            <span>平均工具调用</span>
            <strong>{{ runtimeMetrics?.summary?.avg_tool_calls ?? '-' }}</strong>
            <small>每轮回答平均触发的工具次数。</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'runtime'" class="settings-panel">
        <h3>后端连通性</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>LLM</span>
            <strong>{{ backendStatus?.llm?.available ? '在线' : '离线' }}</strong>
            <small>{{ backendStatus?.llm?.model_name || backendStatus?.llm?.error || '未返回模型信息' }}</small>
          </div>
          <div class="status-card">
            <span>Milvus</span>
            <strong>{{ backendStatus?.milvus?.available ? '在线' : '离线' }}</strong>
            <small>{{ backendStatus?.milvus?.error || '向量检索后端可用' }}</small>
          </div>
          <div class="status-card">
            <span>Elasticsearch</span>
            <strong>{{ backendStatus?.elasticsearch?.available ? '在线' : '离线' }}</strong>
            <small>{{ backendStatus?.elasticsearch?.error || '词法检索后端可用' }}</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'security'" class="settings-panel">
        <h3>安全策略状态</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>总体级别</span>
            <strong>{{ securityPolicy?.mode || '-' }}</strong>
            <small>当前安全模式评估结果。</small>
          </div>
          <div class="status-card">
            <span>Fail-Closed</span>
            <strong>{{ securityPolicy?.fail_closed ? '开启' : '关闭' }}</strong>
            <small>高风险链路是否严格失败关闭。</small>
          </div>
          <div class="status-card">
            <span>审计联动</span>
            <strong>{{ securityPolicy?.audit_enforced ? '启用' : '未启用' }}</strong>
            <small>高风险操作是否强制写审计链路。</small>
          </div>
        </div>
        <ul v-if="securityPolicy?.gaps?.length" class="compact-list">
          <li v-for="(item, index) in securityPolicy.gaps" :key="index">
            <strong>待补齐</strong>
            <span>{{ item }}</span>
          </li>
        </ul>
      </section>

      <section v-if="section === 'mobile'" class="settings-panel">
        <h3>移动认证状态</h3>
        <div class="status-grid two-col">
          <div class="status-card">
            <span>OAuth/OIDC</span>
            <strong>{{ mobileAuthStatus?.enabled ? '已启用' : '未启用' }}</strong>
            <small>{{ mobileAuthStatus?.issuer || '未返回 issuer 信息' }}</small>
          </div>
          <div class="status-card">
            <span>PKCE</span>
            <strong>{{ mobileAuthStatus?.pkce_required ? '强制' : '未强制' }}</strong>
            <small>移动端授权码流程是否要求 PKCE。</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'mobile'" class="settings-panel">
        <h3>推送提供商状态</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>FCM</span>
            <strong>{{ pushProviderStatus?.providers?.fcm?.ready ? '已就绪' : '未就绪' }}</strong>
            <small>{{ pushProviderStatus?.providers?.fcm?.reason || 'Android 推送通道' }}</small>
          </div>
          <div class="status-card">
            <span>APNs</span>
            <strong>{{ pushProviderStatus?.providers?.apns?.ready ? '已就绪' : '未就绪' }}</strong>
            <small>{{ pushProviderStatus?.providers?.apns?.reason || 'iOS 推送通道' }}</small>
          </div>
          <div class="status-card">
            <span>微信小程序</span>
            <strong>{{ pushProviderStatus?.providers?.wechat?.ready ? '已就绪' : '未就绪' }}</strong>
            <small>{{ pushProviderStatus?.providers?.wechat?.reason || '订阅消息通道' }}</small>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  section: string
  isAdmin: boolean
  loadingAdminDiagnostics: boolean
  llmDomainConfig: Record<string, any> | null
  runtimeMetrics: Record<string, any> | null
  retrievalIntegrity: Record<string, any> | null
  securityPolicy: Record<string, any> | null
  mobileAuthStatus: Record<string, any> | null
  pushProviderStatus: Record<string, any> | null
  backendStatus: Record<string, any> | null
  formatPercent: (value?: number | null) => string
  loadAdminDiagnostics: () => Promise<void>
}>()

const title = computed(() => {
  const map: Record<string, string> = {
    models: '模型与策略',
    runtime: '运行时与恢复',
    security: '安全与治理',
    mobile: '移动端接入',
  }
  return map[props.section] || '设置'
})

const summary = computed(() => {
  const map: Record<string, string> = {
    models: '查看企业文档场景下的模型路由、灰度比例和检索完整性状态。',
    runtime: '查看会话恢复、SSE 断连和整体运行指标。',
    security: '查看策略开关、Fail-Closed 状态和高风险链路保护。',
    mobile: '查看 OAuth2/OIDC、推送提供商和当前租户的移动端接入就绪度。',
  }
  return map[props.section] || ''
})
</script>

<style scoped>
.content-block {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.block-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.block-head h2 {
  font-size: 2rem;
  letter-spacing: -0.02em;
}

.block-head p,
.empty-text {
  color: var(--text-secondary);
}

.settings-panel {
  border: 1px solid var(--border-color);
  border-radius: 30px;
  background: color-mix(in srgb, var(--bg-surface) 94%, transparent);
  padding: 24px;
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(18px);
}

.settings-panel h3 {
  font-size: 1.1rem;
  margin-bottom: 18px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.status-grid.two-col {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.status-grid.three-col {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.status-card {
  border-radius: 22px;
  border: 1px solid var(--border-color);
  background: var(--bg-surface-hover);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-card span,
.status-card small {
  color: var(--text-secondary);
}

.status-card strong {
  font-size: 1.06rem;
}

.compact-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.compact-list li {
  list-style: none;
  padding: 14px 16px;
  border-radius: 18px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-color-subtle);
}

.compact-list strong,
.compact-list span {
  display: block;
}

.compact-list span {
  margin-top: 6px;
  color: var(--text-secondary);
}

@media (max-width: 1120px) {
  .status-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .block-head {
    flex-direction: column;
  }
}
</style>
