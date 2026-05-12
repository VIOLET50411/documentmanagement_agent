import { reactive } from "vue"
import { adminApi } from "@/api/admin"

type GenericMap = Record<string, any>

export function useAdminUsers() {
  const state = reactive({
    users: [] as GenericMap[],
    invitations: [] as GenericMap[],
    loadingUsers: false,
    inviting: false,
    savingUserId: "",
    editingUserId: "",
    passwordResetUserId: "",
    deletingUserId: "",
    inviteMessage: "",
    error: "",
    success: "",
    tempPasswordMessage: "",
    editForm: {
      username: "",
      role: "EMPLOYEE",
      department: "",
      level: 2,
      is_active: true,
      email_verified: false,
    },
    inviteForm: {
      email: "",
      role: "EMPLOYEE",
      department: "",
      level: 2,
      expires_hours: 72,
    },
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
    state.success = ""
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
      state.success = `已向 ${payload.email} 发送邀请`
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
    state.success = ""
    try {
      const result = await adminApi.resendInvitation(invitation.invitation_id, 72)
      state.inviteMessage = `已重新发送邀请：${result.email}`
      state.success = `已重发邀请：${result.email}`
      await loadUsers()
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "重发邀请失败。"
    }
  }

  async function revokeInvitation(invitation: GenericMap) {
    state.error = ""
    state.success = ""
    try {
      await adminApi.revokeInvitation(invitation.invitation_id)
      state.inviteMessage = `已撤销邀请：${invitation.email}`
      state.success = `已撤销邀请：${invitation.email}`
      await loadUsers()
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "撤销邀请失败。"
    }
  }

  function startEditUser(user: GenericMap) {
    state.editingUserId = user.id
    state.error = ""
    state.success = ""
    state.editForm.username = user.username || ""
    state.editForm.role = user.role || "EMPLOYEE"
    state.editForm.department = user.department || ""
    state.editForm.level = Number(user.level || roleToLevel(user.role || "EMPLOYEE"))
    state.editForm.is_active = Boolean(user.is_active)
    state.editForm.email_verified = Boolean(user.email_verified)
  }

  function cancelEditUser() {
    state.editingUserId = ""
    state.savingUserId = ""
  }

  async function saveUser(userId: string) {
    state.savingUserId = userId
    state.error = ""
    state.success = ""
    try {
      await adminApi.updateUser(userId, {
        username: state.editForm.username.trim(),
        role: state.editForm.role,
        department: state.editForm.department.trim() || null,
        level: Number(state.editForm.level),
        is_active: state.editForm.is_active,
        email_verified: state.editForm.email_verified,
      })
      state.success = "用户信息已更新。"
      state.editingUserId = ""
      await loadUsers()
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "更新用户失败。"
    } finally {
      state.savingUserId = ""
    }
  }

  async function resetPassword(user: GenericMap) {
    state.passwordResetUserId = user.id
    state.error = ""
    state.success = ""
    state.tempPasswordMessage = ""
    try {
      const result = await adminApi.resetUserPassword(user.id)
      state.success = `已重置 ${result.username} 的密码。`
      state.tempPasswordMessage = `临时密码：${result.temporary_password}`
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "重置密码失败。"
    } finally {
      state.passwordResetUserId = ""
    }
  }

  async function deleteUser(user: GenericMap) {
    state.deletingUserId = user.id
    state.error = ""
    state.success = ""
    state.tempPasswordMessage = ""
    try {
      await adminApi.deleteUser(user.id)
      state.success = `已删除用户：${user.username}`
      await loadUsers()
    } catch (err: any) {
      state.error = err?.response?.data?.detail || "删除用户失败。"
    } finally {
      state.deletingUserId = ""
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
    startEditUser,
    cancelEditUser,
    saveUser,
    resetPassword,
    deleteUser,
    resendInvitation,
    revokeInvitation,
    invitationStatusLabel,
    formatDate,
  }
}
