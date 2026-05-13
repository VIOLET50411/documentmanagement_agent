<template>
  <div class="content-block">
    <div class="block-head">
      <div>
        <h2>{{ title }}</h2>
      </div>
      <button v-if="isAdmin" class="btn btn-ghost btn-sm" @click="loadAdminDiagnostics" :disabled="loadingAdminDiagnostics">
        {{ loadingAdminDiagnostics ? "刷新中..." : "刷新" }}
      </button>
    </div>

    <section v-if="!isAdmin" class="settings-panel">
      <EmptyState
        title="这部分仅管理员可查看。"
        description="切换到管理员账号后，可以查看运行状态、模型策略、安全策略和移动端接入情况。"
      />
    </section>

    <template v-else>
      <StatusMessage
        v-if="adminDiagnosticsMessage"
        :tone="adminDiagnosticsTone"
        :title="adminDiagnosticsTitle"
        :message="adminDiagnosticsMessage"
        dismissible
        @dismiss="clearAdminDiagnosticsMessage"
      />

      <section v-if="section === 'models'" class="settings-panel">
        <h3>企业模型策略</h3>
        <div class="status-grid two-col">
          <div class="status-card">
            <span>企业模型开关</span>
            <strong>{{ llmDomainConfig?.enterprise_enabled ? "已开启" : "未开启" }}</strong>
            <small>控制制度、审计、预算等场景是否优先走企业策略。</small>
          </div>
          <div class="status-card">
            <span>企业模型名称</span>
            <strong>{{ llmDomainConfig?.enterprise_model_name || "-" }}</strong>
            <small>当前企业文档场景使用的主模型。</small>
          </div>
          <div class="status-card">
            <span>灰度比例</span>
            <strong>{{ llmDomainConfig?.enterprise_canary_percent ?? 0 }}%</strong>
            <small>企业策略当前对租户放量的比例。</small>
          </div>
          <div class="status-card">
            <span>最小语料字数</span>
            <strong>{{ llmDomainConfig?.enterprise_corpus_min_chars ?? "-" }}</strong>
            <small>达到该阈值后，才适合启用企业文档专用策略。</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'models'" class="settings-panel">
        <h3>检索体检</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>当前状态</span>
            <strong>{{ retrievalIntegrity?.healthy ? "状态正常" : "需要处理" }}</strong>
            <small>按抽样回查评估当前检索链路是否适合高置信回答。</small>
          </div>
          <div class="status-card">
            <span>体检评分</span>
            <strong>{{ retrievalIntegrity?.score ?? "-" }}</strong>
            <small>综合 ES、Milvus、Graph 的链路完整性结果。</small>
          </div>
          <div class="status-card">
            <span>向量召回率</span>
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
        <h3>运行指标</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>首字返回 P95</span>
            <strong>{{ runtimeMetrics?.summary?.ttft_ms_p95 ?? "-" }} ms</strong>
            <small>回答开始输出前的等待时间。</small>
          </div>
          <div class="status-card">
            <span>完成耗时 P95</span>
            <strong>{{ runtimeMetrics?.summary?.completion_ms_p95 ?? "-" }} ms</strong>
            <small>整轮回答结束的耗时。</small>
          </div>
          <div class="status-card">
            <span>断连次数</span>
            <strong>{{ runtimeMetrics?.summary?.sse_disconnects ?? 0 }}</strong>
            <small>最近采样窗口内的连接中断次数。</small>
          </div>
          <div class="status-card">
            <span>降级比例</span>
            <strong>{{ formatPercent(runtimeMetrics?.summary?.fallback_rate) }}</strong>
            <small>说明真实链路触发备用路径的比例。</small>
          </div>
          <div class="status-card">
            <span>拒绝比例</span>
            <strong>{{ formatPercent(runtimeMetrics?.summary?.deny_rate) }}</strong>
            <small>工具权限网关拦截调用的比例。</small>
          </div>
          <div class="status-card">
            <span>平均工具调用数</span>
            <strong>{{ runtimeMetrics?.summary?.avg_tool_calls ?? "-" }}</strong>
            <small>每轮回答平均触发的工具次数。</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'runtime'" class="settings-panel">
        <h3>后端连通性</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>LLM</span>
            <strong>{{ backendStatus?.llm?.available ? "在线" : "离线" }}</strong>
            <small>{{ backendStatus?.llm?.model_name || backendStatus?.llm?.error || "未返回模型信息" }}</small>
          </div>
          <div class="status-card">
            <span>Milvus</span>
            <strong>{{ backendStatus?.milvus?.available ? "在线" : "离线" }}</strong>
            <small>{{ backendStatus?.milvus?.error || "向量检索后端可用" }}</small>
          </div>
          <div class="status-card">
            <span>Elasticsearch</span>
            <strong>{{ backendStatus?.elasticsearch?.available ? "在线" : "离线" }}</strong>
            <small>{{ backendStatus?.elasticsearch?.error || "词法检索后端可用" }}</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'security'" class="settings-panel">
        <h3>安全策略状态</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>整体级别</span>
            <strong>{{ securityModeLabel(securityPolicy?.mode) }}</strong>
            <small>当前安全模式的综合评估结果。</small>
          </div>
          <div class="status-card">
            <span>严格阻断</span>
            <strong>{{ securityPolicy?.fail_closed ? "已开启" : "已关闭" }}</strong>
            <small>高风险链路是否在异常时直接阻断。</small>
          </div>
          <div class="status-card">
            <span>审计联动</span>
            <strong>{{ securityPolicy?.audit_enforced ? "已启用" : "未启用" }}</strong>
            <small>高风险操作是否强制写入审计链路。</small>
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
            <strong>{{ mobileAuthStatus?.enabled ? "已启用" : "未启用" }}</strong>
            <small>{{ issuerLabel(mobileAuthStatus?.issuer) }}</small>
          </div>
          <div class="status-card">
            <span>PKCE</span>
            <strong>{{ mobileAuthStatus?.pkce_required ? "强制开启" : "未强制" }}</strong>
            <small>移动端授权码流程是否要求 PKCE。</small>
          </div>
        </div>
      </section>

      <section v-if="section === 'mobile'" class="settings-panel">
        <h3>推送通道状态</h3>
        <div class="status-grid three-col">
          <div class="status-card">
            <span>FCM</span>
            <strong>{{ pushProviderStatus?.providers?.fcm?.ready ? "已就绪" : "未就绪" }}</strong>
            <small>{{ providerReasonLabel("fcm", pushProviderStatus?.providers?.fcm?.reason) }}</small>
          </div>
          <div class="status-card">
            <span>微信小程序</span>
            <strong>{{ pushProviderStatus?.providers?.wechat?.ready ? "已就绪" : "未就绪" }}</strong>
            <small>{{ providerReasonLabel("wechat", pushProviderStatus?.providers?.wechat?.reason) }}</small>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue"
import EmptyState from "@/components/common/EmptyState.vue"
import StatusMessage from "@/components/common/StatusMessage.vue"

const props = defineProps<{
  section: string
  isAdmin: boolean
  loadingAdminDiagnostics: boolean
  adminDiagnosticsMessage: string
  llmDomainConfig: Record<string, any> | null
  runtimeMetrics: Record<string, any> | null
  retrievalIntegrity: Record<string, any> | null
  securityPolicy: Record<string, any> | null
  mobileAuthStatus: Record<string, any> | null
  pushProviderStatus: Record<string, any> | null
  backendStatus: Record<string, any> | null
  formatPercent: (value?: number | null) => string
  clearAdminDiagnosticsMessage: () => void
  loadAdminDiagnostics: () => Promise<void>
}>()

const title = computed(() => {
  const map: Record<string, string> = {
    models: "模型与策略",
    runtime: "运行与恢复",
    security: "安全与治理",
    mobile: "移动端接入",
  }
  return map[props.section] || "设置"
})

const adminDiagnosticsTone = computed(() => (props.adminDiagnosticsMessage.includes("失败") ? "error" : "info"))
const adminDiagnosticsTitle = computed(() => (props.adminDiagnosticsMessage.includes("失败") ? "管理员诊断刷新失败" : "管理员诊断状态"))

function securityModeLabel(value?: string | null) {
  const map: Record<string, string> = {
    strict: "严格模式",
    balanced: "平衡模式",
    permissive: "宽松模式",
    audit: "审计优先",
    observe: "观察模式",
  }
  return map[(value || "").toLowerCase()] || value || "-"
}

function issuerLabel(value?: string | null) {
  if (!value) return "未返回认证服务地址"
  try {
    const url = new URL(value)
    return `${url.host}${url.pathname === "/" ? "" : url.pathname}`
  } catch {
    return value
  }
}

function providerReasonLabel(provider: "fcm" | "wechat", reason?: string | null) {
  if (!reason) {
    return provider === "fcm" ? "Android 推送通道" : "订阅消息通道"
  }

  const normalized = reason.toLowerCase()
  const knownMap: Array<[RegExp, string]> = [
    [/missing|not configured|unset/, "关键配置缺失，通道暂时不可用。"],
    [/credential|secret|token/, "推送凭据没有配置完整。"],
    [/permission|forbidden|denied/, "当前凭据权限不足。"],
    [/timeout/, "连接推送服务超时，请稍后重试。"],
    [/network|unreachable|connect/, "暂时无法连接推送服务。"],
    [/disabled|off/, "该推送通道当前被关闭。"],
  ]

  const mapped = knownMap.find(([pattern]) => pattern.test(normalized))
  return mapped?.[1] || reason
}
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
  font-size: 1.25rem;
  font-weight: 600;
}

.block-head p,
.empty-text {
  color: var(--text-secondary);
}

.settings-panel {
  border: none;
  background: transparent;
  padding: 0;
  box-shadow: none;
  backdrop-filter: none;
  border-radius: 0;
  margin-bottom: 32px;
}

.settings-panel h3 {
  font-size: 0.95rem;
  font-weight: 600;
  margin-bottom: 16px;
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

.compact-list strong {
  margin-bottom: 6px;
}

@media (max-width: 900px) {
  .status-grid,
  .status-grid.two-col,
  .status-grid.three-col {
    grid-template-columns: 1fr;
  }

  .block-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
