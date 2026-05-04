import { reactive } from "vue"
import { adminApi } from "@/api/admin"

type GenericMap = Record<string, any>

export function useAdminUsers() {
  const state = reactive({
    users: [] as GenericMap[],
    invitations: [] as GenericMap[],
    loadingUsers: false,
    inviting: false,
    inviteMessage: "",
    error: "",
    inviteForm: {
      email: "",
      role: "EMPLOYEE",
      department: "",
      level: 2,
      expires_hours: 72,
    }
  })

  async function loadUsers() {
    state.loadingUsers = true
    state.error = ""
    try {
      const [usersRes, invitationsRes] = await Promise.all([
        adminApi.listUsers(),
        adminApi.listInvitations({ limit: 20, offset: 0 }),
      ])
      state.users = usersRes
      state.invitations = invitationsRes
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "加载用户数据失败。"
    } finally {
      state.loadingUsers = false
    }
  }

  function roleToLevel(role: string) {
    const map: Record<string, number> = { VIEWER: 1, EMPLOYEE: 2, MANAGER: 5, ADMIN: 9 }
    return map[role] || 2
  }

  async function inviteUser() {
    state.inviting = true
    state.error = ""
    state.inviteMessage = ""
    try {
      const payload = {
        email: state.inviteForm.email,
        role: state.inviteForm.role,
        department: state.inviteForm.department || null,
        level: roleToLevel(state.inviteForm.role),
        expires_hours: 72,
      }
      const result = await adminApi.inviteUser(payload)
      state.inviteMessage = `邀请已发送，令牌：${result.token}`
      state.inviteForm.email = ""
      state.inviteForm.department = ""
      await loadUsers()
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "发送邀请失败。"
    } finally {
      state.inviting = false
    }
  }

  async function resendInvitation(invitation: GenericMap) {
    state.error = ""
    try {
      const result = await adminApi.resendInvitation(invitation.invitation_id, 72)
      state.inviteMessage = `已重新发送邀请：${result.email}`
      await loadUsers()
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "重发邀请失败。"
    }
  }

  async function revokeInvitation(invitation: GenericMap) {
    state.error = ""
    try {
      await adminApi.revokeInvitation(invitation.invitation_id)
      state.inviteMessage = `已撤销邀请：${invitation.email}`
      await loadUsers()
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "撤销邀请失败。"
    }
  }

  function invitationStatusLabel(status: string) {
    const map: Record<string, string> = {
      pending: "待使用",
      used: "已使用",
      expired: "已过期",
      revoked: "已撤销",
    }
    return map[status] || status || "未知"
  }

  function formatDate(value: string | null | undefined) {
    if (!value) return "-"
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
  }

  return {
    state,
    loadUsers,
    inviteUser,
    resendInvitation,
    revokeInvitation,
    invitationStatusLabel,
    formatDate
  }
}
