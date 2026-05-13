import { describe, expect, it } from "vitest"
import {
  backendMonitorErrorLabel,
  checkpointNodeLabel,
  evaluationDifficultyLabel,
  evaluationExclusionReasonLabel,
  evaluationTaskTypeLabel,
  invitationStatusLabel,
  manualSampleSourceLabel,
  readinessStatusLabel,
  roleLabel,
  securityAuditErrorLabel,
  toolDecisionReasonLabel,
  traceSourceLabel,
  traceStatusLabel,
  userLevelLabel,
} from "../adminUi"

describe("adminUi labels", () => {
  it("maps common admin labels to readable Chinese copy", () => {
    expect(roleLabel("ADMIN")).toBe("超级管理员")
    expect(invitationStatusLabel("pending")).toBe("待接受")
    expect(userLevelLabel(5)).toBe("L5 / 管理员")
    expect(readinessStatusLabel("degraded")).toBe("已降级")
    expect(checkpointNodeLabel("tool_call")).toBe("工具调用")
    expect(toolDecisionReasonLabel("rbac_allow")).toBe("角色权限允许")
    expect(traceStatusLabel("streaming")).toBe("系统正在生成回答")
    expect(traceSourceLabel("tool_gateway")).toBe("工具网关")
    expect(manualSampleSourceLabel("retrieval_debug")).toBe("检索调试台")
    expect(evaluationTaskTypeLabel("follow_up")).toBe("追问")
    expect(evaluationDifficultyLabel("grounded")).toBe("需对照原文")
    expect(evaluationExclusionReasonLabel("excluded_by_sample_limit")).toBe("样本数量超了，这次没带上")
  })

  it("keeps admin error copy consistent", () => {
    expect(backendMonitorErrorLabel("system")).toBe("系统状态暂时没有加载出来，请稍后再试。")
    expect(backendMonitorErrorLabel("retrieval")).toBe("检索健康度暂时没有加载出来，请稍后再试。")
    expect(backendMonitorErrorLabel("toolExport")).toBe("导出当前统计失败，请稍后再试。")
    expect(securityAuditErrorLabel()).toBe("安全记录暂时没有加载出来，请稍后再试。")
  })
})
