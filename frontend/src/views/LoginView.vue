<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="bg-orb bg-orb-1"></div>
      <div class="bg-orb bg-orb-2"></div>
      <div class="bg-orb bg-orb-3"></div>
    </div>

    <div class="login-container card-glass animate-fade-in">
      <div class="login-header">
        <span class="login-logo">DM</span>
        <h1 class="login-title">DocMind Agent</h1>
        <p class="login-subtitle">企业管理文档智能问答平台</p>
      </div>

      <form class="login-form" @submit.prevent="handleSubmit">
        <div class="form-group">
          <label for="username">用户名</label>
          <input id="username" v-model="form.username" type="text" class="input" placeholder="请输入用户名" required autocomplete="username" />
        </div>

        <div class="form-group" v-if="isRegister">
          <label for="email">邮箱</label>
          <input id="email" v-model="form.email" type="email" class="input" placeholder="请输入企业邮箱" />
        </div>

        <div class="form-row" v-if="isRegister">
          <div class="form-group grow">
            <label for="verifyCode">邮箱验证码</label>
            <input id="verifyCode" v-model="form.verification_code" type="text" class="input" placeholder="请输入验证码" />
          </div>
          <button type="button" class="btn btn-outline code-btn" :disabled="sendingCode || !form.email" @click="sendCode">
            {{ sendingCode ? '发送中...' : '发送验证码' }}
          </button>
        </div>

        <div class="form-group" v-if="isRegister">
          <label for="inviteToken">邀请码</label>
          <input id="inviteToken" v-model="form.invite_token" type="text" class="input" placeholder="企业内部注册请填写邀请码" />
        </div>

        <div class="form-group" v-if="isRegister">
          <label for="department">部门</label>
          <input id="department" v-model="form.department" type="text" class="input" placeholder="请输入所属部门，可选" />
        </div>

        <div class="form-group">
          <label for="password">密码</label>
          <input id="password" v-model="form.password" type="password" class="input" placeholder="请输入密码" required autocomplete="current-password" />
        </div>

        <p v-if="message" class="success-msg">{{ message }}</p>
        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>

        <button type="submit" class="btn btn-primary btn-lg login-btn" :disabled="isLoading">
          {{ isLoading ? '处理中...' : isRegister ? '注册账号' : '登录' }}
        </button>

        <div class="form-actions">
          <p class="toggle-mode">
            {{ isRegister ? '已有账号？' : '没有账号？' }}
            <a href="#" @click.prevent="isRegister = !isRegister">{{ isRegister ? '返回登录' : '使用邀请注册' }}</a>
          </p>
          <a href="#" class="secondary-link" @click.prevent="requestReset">忘记密码</a>
        </div>

        <div class="demo-tip">
          <p>首次进入可使用演示账号：</p>
          <p><code>admin_demo</code> / <code>Password123</code></p>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const isRegister = ref(false)
const isLoading = ref(false)
const sendingCode = ref(false)
const errorMsg = ref('')
const message = ref('')
const form = reactive({ username: '', password: '', email: '', department: '', invite_token: '', verification_code: '' })

async function handleSubmit() {
  isLoading.value = true
  errorMsg.value = ''
  message.value = ''
  try {
    if (isRegister.value) {
      await authStore.register(form)
      message.value = '注册成功。若邮箱尚未验证，请先完成验证码验证后登录。'
      isRegister.value = false
    } else {
      await authStore.login(form.username, form.password)
      router.push('/chat')
    }
  } catch (error) {
    errorMsg.value = error.response?.data?.detail || '操作失败，请重试'
  } finally {
    isLoading.value = false
  }
}

async function sendCode() {
  if (!form.email) return
  sendingCode.value = true
  errorMsg.value = ''
  message.value = ''
  try {
    const res = await authStore.sendVerificationCode({ email: form.email, username: form.username || undefined })
    message.value = res.message || '验证码已发送'
  } catch (error) {
    errorMsg.value = error.response?.data?.detail || '验证码发送失败'
  } finally {
    sendingCode.value = false
  }
}

async function requestReset() {
  if (!form.email) {
    errorMsg.value = '请输入邮箱后再申请密码重置'
    return
  }
  errorMsg.value = ''
  try {
    const res = await authStore.requestPasswordReset(form.email)
    message.value = res.message || '如邮箱存在，已发送重置说明'
  } catch (error) {
    errorMsg.value = error.response?.data?.detail || '重置请求失败'
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  padding: 24px;
}

.login-bg {
  position: absolute;
  inset: 0;
  overflow: hidden;
  z-index: 0;
}

.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(96px);
  opacity: 0.26;
  animation: float 20s ease-in-out infinite;
}

.bg-orb-1 {
  width: 420px;
  height: 420px;
  background: #c89a63;
  top: -140px;
  left: -120px;
}

.bg-orb-2 {
  width: 340px;
  height: 340px;
  background: #5b4d3c;
  bottom: -100px;
  right: -80px;
  animation-delay: 5s;
}

.bg-orb-3 {
  width: 220px;
  height: 220px;
  background: #e5cfaf;
  top: 44%;
  left: 62%;
  animation-delay: 10s;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0); }
  25% { transform: translate(26px, -18px); }
  50% { transform: translate(-18px, 28px); }
  75% { transform: translate(20px, 18px); }
}

.login-container {
  position: relative;
  z-index: 1;
  width: 480px;
  max-width: 92vw;
  padding: 36px;
  border-radius: 32px;
}

.login-header {
  text-align: center;
  margin-bottom: 28px;
}

.login-logo {
  width: 60px;
  height: 60px;
  margin: 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 20px;
  background: linear-gradient(135deg, #2b241b 0%, #5a4731 35%, #d09d5f 100%);
  color: #fff5e7;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.login-title {
  font-size: clamp(2rem, 5vw, 2.6rem);
  line-height: 1.04;
  letter-spacing: -0.03em;
  margin-top: 16px;
}

.login-subtitle {
  color: var(--text-secondary);
  font-size: 0.95rem;
  margin-top: 10px;
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
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
}

.login-btn,
.code-btn {
  width: 100%;
}

.code-btn {
  width: 152px;
}

.form-actions {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  align-items: center;
}

.toggle-mode,
.secondary-link {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.success-msg {
  color: var(--color-success);
  font-size: var(--text-sm);
}

.error-msg {
  color: var(--color-danger);
  font-size: var(--text-sm);
}

.demo-tip {
  padding: 16px 18px;
  border-radius: 20px;
  background: var(--bg-input);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  border: 1px solid var(--border-color);
}

@media (max-width: 720px) {
  .login-container {
    padding: 28px 22px;
  }

  .form-row {
    flex-direction: column;
    align-items: stretch;
  }

  .code-btn {
    width: 100%;
  }

  .form-actions {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
