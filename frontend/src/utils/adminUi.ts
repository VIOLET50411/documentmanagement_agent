export function getApiErrorMessage(err: any, fallback: string) {
  const detail = err?.response?.data?.detail
  if (typeof detail === "string" && detail.trim()) return detail
  return fallback
}

export function roleLabel(role?: string | null) {
  const map: Record<string, string> = {
    VIEWER: "只读用户",
    EMPLOYEE: "普通成员",
    MANAGER: "管理员",
    ADMIN: "超级管理员",
  }
  return map[role || ""] || role || "未知"
}

export function securitySeverityLabel(value?: string | null) {
  const map: Record<string, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
  }
  return map[(value || "").toLowerCase()] || value || "未知"
}

export function securityResultLabel(value?: string | null) {
  const map: Record<string, string> = {
    ok: "已放行",
    blocked: "已拦截",
    error: "执行出错",
  }
  return map[(value || "").toLowerCase()] || value || "未知"
}

export function securityEventTypeLabel(value?: string | null) {
  const map: Record<string, string> = {
    input_blocked: "输入内容被拦截",
    output_blocked: "输出内容被拦截",
    tool_denied: "工具调用被拦截",
    tool_ask: "工具调用需要确认",
    login_failed: "登录失败",
    permission_denied: "权限不足",
  }
  return map[value || ""] || value || "安全事件"
}

export function pipelineStatusLabel(status?: string | null) {
  const map: Record<string, string> = {
    failed_family: "失败或部分失败",
    queued: "等待中",
    parsing: "解析中",
    chunking: "切分中",
    indexing: "入库中",
    retrying: "重试中",
    ready: "已完成",
    partial_failed: "部分失败",
    failed: "失败",
  }
  return map[status || ""] || status || "未知状态"
}

export function readinessStatusLabel(value?: string | null) {
  const map: Record<string, string> = {
    ready: "已就绪",
    healthy: "状态健康",
    warning: "需要关注",
    degraded: "已降级",
    blocked: "已阻塞",
    not_ready: "未就绪",
  }
  return map[(value || "").toLowerCase()] || value || "未知"
}

export function checkpointNodeLabel(value?: string | null) {
  const map: Record<string, string> = {
    thinking: "问题理解",
    searching: "知识检索",
    reading: "证据读取",
    tool_call: "工具调用",
    streaming: "回答生成",
    final: "结果收尾",
  }
  return map[(value || "").toLowerCase()] || value || "-"
}

export function blockerLabel(value?: string | null) {
  const map: Record<string, string> = {
    llm_unavailable: "大模型服务不可用",
    retrieval_unhealthy: "检索链路异常",
    corpus_not_ready: "公开语料尚未就绪",
    security_policy_gap: "安全策略未补齐",
    mobile_auth_unready: "移动认证未就绪",
  }
  return map[(value || "").toLowerCase()] || value || "未命名阻塞项"
}

export function toolDecisionReasonLabel(value?: string | null) {
  const map: Record<string, string> = {
    rbac_allow: "角色权限允许",
    rbac_deny: "角色权限不允许",
    security_audit_blocked: "安全审计拦截",
    security_audit_ask: "安全审计要求确认",
    tool_spec_missing_confirmation: "工具说明要求先确认",
    registry_missing: "工具目录中没有找到定义",
  }
  return map[(value || "").toLowerCase()] || value || "未说明原因"
}

export function invitationStatusLabel(status?: string | null) {
  const map: Record<string, string> = {
    pending: "待接受",
    used: "已接受",
    expired: "已过期",
    revoked: "已撤销",
  }
  return map[(status || "").toLowerCase()] || status || "未知状态"
}

export function userLevelLabel(level: number | string | null | undefined) {
  const value = Number(level)
  if (Number.isNaN(value)) return "-"
  if (value >= 9) return `L${value} / 超级管理员`
  if (value >= 5) return `L${value} / 管理员`
  if (value >= 2) return `L${value} / 普通成员`
  return `L${value} / 只读`
}

export function traceStatusLabel(status?: string | null) {
  const map: Record<string, string> = {
    thinking: "系统正在理解问题",
    searching: "系统正在查找资料",
    reading: "系统正在读取资料",
    tool_call: "系统正在调用工具",
    streaming: "系统正在生成回答",
    done: "这一步已完成",
    error: "这一步失败了",
  }
  return map[(status || "").toLowerCase()] || status || "运行事件"
}

export function traceSourceLabel(source?: string | null) {
  const map: Record<string, string> = {
    runtime: "运行时",
    agent_runtime_v2: "智能体运行时",
    llm: "大模型",
    retrieval: "检索链路",
    tool_gateway: "工具网关",
    security_audit: "安全审计",
  }
  return map[(source || "").toLowerCase()] || source || "运行时"
}

export function manualSampleSourceLabel(value?: string | null) {
  const map: Record<string, string> = {
    retrieval_debug: "检索调试台",
    manual_entry: "人工录入",
  }
  return map[(value || "").toLowerCase()] || value || "未知"
}

export function evaluationTaskTypeLabel(value?: string | null) {
  const map: Record<string, string> = {
    summary: "总结理解",
    grounded: "有明确依据",
    follow_up: "追问",
    compare: "对比",
    version: "版本差异",
    manual_debug: "手工样本",
  }
  return map[(value || "").toLowerCase()] || value || "未知类型"
}

export function evaluationDifficultyLabel(value?: string | null) {
  const map: Record<string, string> = {
    basic: "基础",
    grounded: "需对照原文",
    advanced: "进阶",
    manual: "手工",
  }
  return map[(value || "").toLowerCase()] || value || "未知难度"
}

export function evaluationExclusionReasonLabel(value?: string | null) {
  const map: Record<string, string> = {
    no_recent_evaluation: "最近这轮没有抽到",
    changed_after_latest_evaluation: "样本有更新，需要重新检查",
    excluded_by_sample_limit: "样本数量超了，这次没带上",
    not_in_latest_dataset: "这次数据集里没有它",
  }
  return map[(value || "").toLowerCase()] || "这次没参与"
}

export function backendMonitorErrorLabel(kind: "system" | "retrieval" | "publicCorpusLoad" | "publicCorpusTask" | "publicCorpusPoll" | "publicCorpusStart" | "toolExport") {
  const map = {
    system: "系统状态暂时没有加载出来，请稍后再试。",
    retrieval: "检索健康度暂时没有加载出来，请稍后再试。",
    publicCorpusLoad: "公开语料导出结果暂时没有加载出来，请稍后再试。",
    publicCorpusTask: "公开语料导出没有成功完成，请稍后再试。",
    publicCorpusPoll: "导出任务已经发起，但暂时拿不到进度。请稍后再试。",
    publicCorpusStart: "公开语料导出没有成功发起，请稍后再试。",
    toolExport: "导出当前统计失败，请稍后再试。",
  } satisfies Record<string, string>
  return map[kind]
}

export function securityAuditErrorLabel() {
  return "安全记录暂时没有加载出来，请稍后再试。"
}
