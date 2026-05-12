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
      <p v-if="state.success" class="report-meta success">{{ state.success }}</p>
      <p v-if="state.error" class="report-meta error">{{ state.error }}</p>
      <p v-if="state.tempPasswordMessage" class="report-meta temp-password">{{ state.tempPasswordMessage }}</p>
      <table v-if="state.users.length" class="data-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>邮箱</th>
            <th>角色</th>
            <th>部门</th>
            <th>级别</th>
            <th>账号状态</th>
            <th>邮箱状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in state.users" :key="user.id">
            <td>
              <template v-if="state.editingUserId === user.id">
                <input v-model="state.editForm.username" class="input table-input" type="text" />
              </template>
              <template v-else>{{ user.username }}</template>
            </td>
            <td>{{ user.email }}</td>
            <td>
              <template v-if="state.editingUserId === user.id">
                <select v-model="state.editForm.role" class="input table-input">
                  <option value="VIEWER">VIEWER</option>
                  <option value="EMPLOYEE">EMPLOYEE</option>
                  <option value="MANAGER">MANAGER</option>
                  <option value="ADMIN">ADMIN</option>
                </select>
              </template>
              <template v-else>{{ user.role }}</template>
            </td>
            <td>
              <template v-if="state.editingUserId === user.id">
                <input v-model="state.editForm.department" class="input table-input" type="text" placeholder="未设置" />
              </template>
              <template v-else>{{ user.department || "未设置" }}</template>
            </td>
            <td>
              <template v-if="state.editingUserId === user.id">
                <input v-model.number="state.editForm.level" class="input table-input level-input" type="number" min="1" max="9" />
              </template>
              <template v-else>{{ user.level }}</template>
            </td>
            <td>
              <template v-if="state.editingUserId === user.id">
                <select v-model="state.editForm.is_active" class="input table-input">
                  <option :value="true">启用</option>
                  <option :value="false">停用</option>
                </select>
              </template>
              <template v-else>{{ user.is_active ? "启用" : "停用" }}</template>
            </td>
            <td>
              <template v-if="state.editingUserId === user.id">
                <select v-model="state.editForm.email_verified" class="input table-input">
                  <option :value="true">已验证</option>
                  <option :value="false">未验证</option>
                </select>
              </template>
              <template v-else>{{ user.email_verified ? "已验证" : "未验证" }}</template>
            </td>
            <td class="action-group">
              <template v-if="state.editingUserId === user.id">
                <button class="btn btn-primary" :disabled="state.savingUserId === user.id" @click="saveUser(user.id)">
                  {{ state.savingUserId === user.id ? "保存中..." : "保存" }}
                </button>
                <button class="btn btn-ghost" :disabled="state.savingUserId === user.id" @click="cancelEditUser">取消</button>
              </template>
              <template v-else>
                <button class="btn btn-ghost" @click="startEditUser(user)">编辑</button>
                <button class="btn btn-ghost" :disabled="state.passwordResetUserId === user.id" @click="resetPassword(user)">
                  {{ state.passwordResetUserId === user.id ? "重置中..." : "重置密码" }}
                </button>
                <button class="btn btn-danger" :disabled="state.deletingUserId === user.id" @click="deleteUser(user)">
                  {{ state.deletingUserId === user.id ? "删除中..." : "删除用户" }}
                </button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-text">暂无用户数据。</p>

      <h2 class="sub-section-title">邀请记录</h2>
      <table v-if="state.invitations.length" class="data-table">
        <thead>
          <tr>
            <th>邮箱</th>
            <th>角色</th>
            <th>部门</th>
            <th>状态</th>
            <th>到期时间</th>
            <th>操作</th>
          </tr>
        </thead>
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
import { onMounted } from "vue"
import { useAdminUsers } from "./composables/useAdminUsers"

const {
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
} = useAdminUsers()

onMounted(() => {
  loadUsers()
})
</script>

<style scoped>
.success {
  color: #18794e;
}

.error {
  color: #c0392b;
}

.temp-password {
  color: #8a5cf6;
  font-weight: 600;
}

.table-input {
  min-width: 96px;
}

.level-input {
  width: 88px;
}
</style>
