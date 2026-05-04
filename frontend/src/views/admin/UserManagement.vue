<template>
  <div class="tab-content animate-fade-in">
    <div class="card section-card">
      <h2>租户用户</h2>
      <form class="invite-form" @submit.prevent="inviteUser">
        <input v-model="state.inviteForm.email" class="input" type="email" placeholder="受邀人邮箱" required />
        <select v-model="state.inviteForm.role" class="input">
          <option value="VIEWER">VIEWER</option>
          <option value="EMPLOYEE">EMPLOYEE</option>
          <option value="MANAGER">MANAGER</option>
          <option value="ADMIN">ADMIN</option>
        </select>
        <input v-model="state.inviteForm.department" class="input" type="text" placeholder="部门（可选）" />
        <button class="btn btn-primary" :disabled="state.inviting">{{ state.inviting ? "发送中..." : "发送邀请" }}</button>
      </form>
      <p v-if="state.inviteMessage" class="report-meta">{{ state.inviteMessage }}</p>
      <table v-if="state.users.length" class="data-table">
        <thead><tr><th>用户名</th><th>邮箱</th><th>角色</th><th>部门</th><th>级别</th><th>邮箱状态</th></tr></thead>
        <tbody>
          <tr v-for="user in state.users" :key="user.id">
            <td>{{ user.username }}</td>
            <td>{{ user.email }}</td>
            <td>{{ user.role }}</td>
            <td>{{ user.department || "未设置" }}</td>
            <td>{{ user.level }}</td>
            <td>{{ user.email_verified ? "已验证" : "未验证" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无用户数据。</p>

      <h2 class="sub-section-title">邀请记录</h2>
      <table v-if="state.invitations.length" class="data-table">
        <thead><tr><th>邮箱</th><th>角色</th><th>部门</th><th>状态</th><th>到期时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="inv in state.invitations" :key="inv.invitation_id">
            <td>{{ inv.email }}</td>
            <td>{{ inv.role }}</td>
            <td>{{ inv.department || "未设置" }}</td>
            <td>{{ invitationStatusLabel(inv.status) }}</td>
            <td>{{ formatDate(inv.expires_at) }}</td>
            <td class="action-group">
              <button class="btn btn-ghost" :disabled="inv.status !== 'pending'" @click="resendInvitation(inv)">重发</button>
              <button class="btn btn-danger" :disabled="inv.status !== 'pending'" @click="revokeInvitation(inv)">撤销</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无邀请记录。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAdminUsers } from './composables/useAdminUsers'

const {
  state,
  loadUsers,
  inviteUser,
  resendInvitation,
  revokeInvitation,
  invitationStatusLabel,
  formatDate
} = useAdminUsers()

onMounted(() => {
  loadUsers()
})
</script>
