<template>
  <div class="login-page">
    <div class="login-container animate-fade-in">
      <div class="login-header">
        <h1 class="login-logo-text">DocMind</h1>
        <p class="login-subtitle">企业管理文档智能问答平台</p>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
        <!-- LOGIN MODE -->
        <template v-if="mode === 'login'">
          <div class="form-group">
            <label for="username">用户名</label>
            <input id="username" v-model="form.username" type="text" class="input" placeholder="请输入用户名" required autocomplete="username" />
          </div>
          <div class="form-group">
            <label for="password">密码</label>
            <input id="password" v-model="form.password" type="password" class="input" placeholder="请输入密码" required autocomplete="current-password" />
          </div>
        </template>

        <!-- REGISTER MODE -->
        <template v-else-if="mode === 'register'">
          <div class="form-group">
            <label for="reg_username">用户名</label>
            <input id="reg_username" v-model="form.username" type="text" class="input" placeholder="设置您的用户名" required autocomplete="username" />
          </div>
          <div class="form-group">
            <label for="email">邮箱</label>
            <input id="email" v-model="form.email" type="email" class="input" placeholder="请输入企业邮箱" required />
          </div>
          <div class="form-row">
            <div class="form-group grow">
              <label for="verifyCode">邮箱验证码</label>
              <input id="verifyCode" v-model="form.verification_code" type="text" class="input" placeholder="请输入验证码" required />
            </div>
            <button type="button" class="btn btn-outline code-btn" :disabled="sendingCode || !form.email" @click="sendCode">
              {{ sendingCode ? '发送中...' : '发送验证码' }}
            </button>
          </div>
          <div class="form-group">
            <label for="department">部门 (可选)</label>
            <input id="department" v-model="form.department" type="text" class="input" placeholder="请输入所属部门" />
          </div>
          <div class="form-group">
            <label for="inviteToken">邀请码 (内部注册必填)</label>
            <input id="inviteToken" v-model="form.invite_token" type="text" class="input" placeholder="企业内部注册邀请码" />
          </div>
          <div class="form-group">
            <label for="reg_password">密码</label>
            <input id="reg_password" v-model="form.password" type="password" class="input" placeholder="设置密码 (至少 8 位)" required autocomplete="new-password" />
          </div>
        </template>

        <!-- RESET MODE -->
        <template v-else-if="mode === 'reset'">
          <div class="form-group">
            <label for="reset_email">重置邮箱</label>
            <input id="reset_email" v-model="form.email" type="email" class="input" placeholder="请输入需要重置密码的邮箱" required />
          </div>
        </template>

        <p v-if="message" class="success-msg">{{ message }}</p>
        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>

        <button type="submit" class="btn btn-primary btn-lg login-btn" :disabled="isLoading">
          {{ submitButtonText }}
        </button>

        <div class="form-actions">
          <p class="toggle-mode" v-if="mode === 'login'">
            没有账号？<a href="#" @click.prevent="switchMode('register')">注册新账号</a>
          </p>
          <p class="toggle-mode" v-else>
            已有账号？<a href="#" @click.prevent="switchMode('login')">返回登录</a>
          </p>
          <a href="#" class="secondary-link" v-if="mode === 'login'" @click.prevent="switchMode('reset')">忘记密码</a>
        </div>

        <div class="demo-tip" v-if="mode === 'login'">
          <p>首次进入可使用演示账号：</p>
          <p><code>admin_demo</code> / <code>Password123</code></p>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

type ViewMode = 'login' | 'register' | 'reset';

const router = useRouter()
const authStore = useAuthStore()

const mode = ref<ViewMode>('login')
const isLoading = ref(false)
const sendingCode = ref(false)
const errorMsg = ref('')
const message = ref('')

const form = reactive({ 
  username: '', 
  password: '', 
  email: '', 
  department: '', 
  invite_token: '', 
  verification_code: '' 
})

const submitButtonText = computed(() => {
  if (isLoading.value) return '处理中...'
  if (mode.value === 'login') return '登录'
  if (mode.value === 'register') return '注册账号'
  return '发送重置邮件'
})

function switchMode(newMode: ViewMode) {
  mode.value = newMode
  errorMsg.value = ''
  message.value = ''
  // Keep form data between modes to save typing
}

function validateForm(): boolean {
  errorMsg.value = ''
  if (mode.value === 'login') {
    if (!form.username.trim()) { errorMsg.value = '用户名不能为空'; return false; }
    if (!form.password) { errorMsg.value = '密码不能为空'; return false; }
  } else if (mode.value === 'register') {
    if (!form.username.trim()) { errorMsg.value = '用户名不能为空'; return false; }
    if (!form.email.includes('@')) { errorMsg.value = '请输入有效的邮箱地址'; return false; }
    if (!form.verification_code) { errorMsg.value = '请填写邮箱收到的验证码'; return false; }
    if (form.password.length < 8) { errorMsg.value = '密码长度不能少于 8 位'; return false; }
  } else if (mode.value === 'reset') {
    if (!form.email.includes('@')) { errorMsg.value = '请输入有效的邮箱地址'; return false; }
  }
  return true;
}

async function handleSubmit() {
  if (!validateForm()) return;
  
  isLoading.value = true
  errorMsg.value = ''
  message.value = ''
  
  try {
    if (mode.value === 'register') {
      await authStore.register(form)
      message.value = '注册成功，即将跳转登录'
      setTimeout(() => switchMode('login'), 1500)
    } else if (mode.value === 'login') {
      await authStore.login(form.username, form.password)
      router.push('/chat')
    } else if (mode.value === 'reset') {
      const res = await authStore.requestPasswordReset(form.email)
      message.value = res.message || '重置说明已发送至您的邮箱'
    }
  } catch (error: any) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') {
      errorMsg.value = detail
    } else if (Array.isArray(detail) && detail.length > 0 && detail[0].msg) {
      errorMsg.value = detail[0].msg
    } else {
      errorMsg.value = mode.value === 'login' ? '账号或密码错误' : '请求失败，请稍后重试'
    }
  } finally {
    isLoading.value = false
  }
}

async function sendCode() {
  if (!form.email.includes('@')) {
    errorMsg.value = '请输入有效的邮箱地址后再发送验证码'
    return
  }
  sendingCode.value = true
  errorMsg.value = ''
  message.value = ''
  try {
    const res = await authStore.sendVerificationCode({ email: form.email, username: form.username || undefined })
    message.value = res.message || '验证码已发送至邮箱，请查收'
  } catch (error: any) {
    errorMsg.value = error.response?.data?.detail || '验证码发送频繁或失败，请稍后重试'
  } finally {
    sendingCode.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-container {
  width: 400px;
  max-width: 100%;
  padding: 40px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.login-header {
  text-align: center;
  margin-bottom: 32px;
}

.login-logo-text {
  font-family: var(--font-heading);
  font-size: 2.5rem;
  font-weight: 400;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: -0.02em;
}

.login-subtitle {
  color: var(--text-secondary);
  font-size: 0.95rem;
  margin-top: 8px;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-row {
  display: flex;
  align-items: end;
  gap: var(--space-3);
}

.grow {
  flex: 1;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.login-btn,
.code-btn {
  height: 44px;
  border-radius: 12px;
}

.login-btn {
  margin-top: var(--space-2);
}

.form-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: var(--space-2);
  font-size: 0.875rem;
}

.toggle-mode a,
.secondary-link {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 500;
}

.toggle-mode a:hover,
.secondary-link:hover {
  text-decoration: underline;
}

.demo-tip {
  margin-top: var(--space-5);
  padding: var(--space-3);
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
  font-size: 0.85rem;
  color: var(--text-secondary);
  text-align: center;
}

.demo-tip p {
  margin: 4px 0;
}

.demo-tip code {
  background: var(--bg-surface);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--text-primary);
}

.error-msg {
  color: var(--color-danger);
  font-size: 0.875rem;
  background: rgba(220, 38, 38, 0.1);
  padding: 10px;
  border-radius: 8px;
}

.success-msg {
  color: var(--color-success);
  font-size: 0.875rem;
  background: rgba(16, 185, 129, 0.1);
  padding: 10px;
  border-radius: 8px;
}
</style>
