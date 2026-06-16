<template>
  <div class="login-page">
    <div class="bg-blob blob-1"></div>
    <div class="bg-blob blob-2"></div>
    <div class="bg-blob blob-3"></div>
    <div class="login-container animate-fade-in">
      <div class="login-header">
        <h1 class="login-hero-title">DocMind</h1>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
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

        <template v-else-if="mode === 'register'">
          <div class="form-group">
            <label for="reg_username">用户名</label>
            <input id="reg_username" v-model="form.username" type="text" class="input" placeholder="请设置用户名" required autocomplete="username" />
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
            <label for="department">部门（可选）</label>
            <input id="department" v-model="form.department" type="text" class="input" placeholder="请输入所属部门" />
          </div>
          <div class="form-group">
            <label for="inviteToken">邀请码（内部注册必填）</label>
            <input id="inviteToken" v-model="form.invite_token" type="text" class="input" placeholder="请输入内部邀请码" />
          </div>
          <div class="form-group">
            <label for="reg_password">密码</label>
            <input id="reg_password" v-model="form.password" type="password" class="input" placeholder="请设置密码（至少 8 位）" required autocomplete="new-password" />
          </div>
        </template>

        <template v-else-if="mode === 'reset'">
          <div class="form-group">
            <label for="reset_email">重置邮箱</label>
            <input id="reset_email" v-model="form.email" type="email" class="input" placeholder="请输入需要重置密码的邮箱" required />
          </div>
        </template>

        <StatusMessage v-if="message" tone="success" :message="message" />
        <StatusMessage v-if="errorMsg" tone="error" :message="errorMsg" />

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

      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import StatusMessage from '@/components/common/StatusMessage.vue'
import { useAuthStore } from '@/stores/auth'

type ViewMode = 'login' | 'register' | 'reset'

const brandLogoUrl = new URL('../../../logo.jpg', import.meta.url).href
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
  verification_code: '',
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
}

function validateForm(): boolean {
  errorMsg.value = ''
  if (mode.value === 'login') {
    if (!form.username.trim()) {
      errorMsg.value = '用户名不能为空'
      return false
    }
    if (!form.password) {
      errorMsg.value = '密码不能为空'
      return false
    }
  } else if (mode.value === 'register') {
    if (!form.username.trim()) {
      errorMsg.value = '用户名不能为空'
      return false
    }
    if (!form.email.includes('@')) {
      errorMsg.value = '请输入有效的邮箱地址'
      return false
    }
    if (!form.verification_code) {
      errorMsg.value = '请填写邮箱收到的验证码'
      return false
    }
    if (form.password.length < 8) {
      errorMsg.value = '密码长度不能少于 8 位'
      return false
    }
  } else if (mode.value === 'reset') {
    if (!form.email.includes('@')) {
      errorMsg.value = '请输入有效的邮箱地址'
      return false
    }
  }
  return true
}

async function handleSubmit() {
  if (!validateForm()) return

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
    errorMsg.value = error.response?.data?.detail || '验证码发送过于频繁或失败，请稍后重试'
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
  background: var(--bg-body);
  position: relative;
  overflow: hidden;
}

.bg-blob {
  position: absolute;
  filter: blur(80px);
  z-index: 0;
  opacity: 0.5;
  border-radius: 50%;
  animation: blob-float 20s infinite alternate ease-in-out;
  pointer-events: none;
}

.blob-1 {
  width: 500px;
  height: 500px;
  background: color-mix(in srgb, var(--color-primary) 40%, transparent);
  top: -100px;
  left: -100px;
  animation-delay: 0s;
}

.blob-2 {
  width: 400px;
  height: 400px;
  background: color-mix(in srgb, var(--color-success) 30%, transparent);
  bottom: -50px;
  right: -50px;
  animation-delay: -5s;
}

.blob-3 {
  width: 300px;
  height: 300px;
  background: color-mix(in srgb, var(--color-warning) 30%, transparent);
  top: 40%;
  left: 60%;
  animation-delay: -10s;
}

@keyframes blob-float {
  0% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(80px, 40px) scale(1.1); }
  100% { transform: translate(-40px, 80px) scale(0.9); }
}

.login-container {
  position: relative;
  z-index: 1;
  width: 440px;
  max-width: 100%;
  padding: 40px;
  background: color-mix(in srgb, var(--bg-surface) 70%, transparent);
  backdrop-filter: blur(24px) saturate(150%);
  -webkit-backdrop-filter: blur(24px) saturate(150%);
  border: 1px solid color-mix(in srgb, var(--border-color) 60%, transparent);
  border-radius: 24px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.08);
}

.login-header {
  margin-bottom: 32px;
}

.login-hero-title {
  margin: 0;
  font-size: 2.5rem;
  line-height: 1.2;
  font-family: var(--font-heading);
  font-weight: 700;
  text-align: center;
  color: var(--color-primary);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.form-row {
  display: flex;
  gap: 12px;
  align-items: end;
}

.grow {
  flex: 1;
}

.input {
  width: 100%;
}

.code-btn {
  height: 42px;
  white-space: nowrap;
}

.login-btn {
  width: 100%;
  margin-top: 8px;
}

.form-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 14px;
}

.toggle-mode,
.secondary-link {
  color: var(--text-secondary);
}

.toggle-mode a,
.secondary-link {
  color: var(--text-link);
  text-decoration: none;
}

@media (max-width: 640px) {
  .login-container {
    padding: 24px;
  }

  .brand-lockup {
    align-items: flex-start;
  }

  .login-logo {
    width: 56px;
    height: 56px;
  }

  .login-logo-text {
    font-size: 1.55rem;
  }

  .form-row {
    flex-direction: column;
    align-items: stretch;
  }

  .code-btn {
    width: 100%;
  }
}
</style>
