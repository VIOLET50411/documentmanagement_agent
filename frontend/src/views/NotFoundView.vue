<template>
  <div class="not-found">
    <div class="nf-content animate-fade-in">
      <span class="nf-code">404</span>
      <h2>页面不存在</h2>
      <p>你访问的页面可能已被移除，或者当前路由地址不正确。</p>
      <router-link to="/" class="btn btn-primary">返回首页</router-link>
    </div>
  </div>
</template>

<style scoped>
.not-found { display: flex; align-items: center; justify-content: center; height: 100vh; }
.nf-content { text-align: center; }
.nf-code { font-size: 6rem; font-weight: 800; color: var(--color-primary); opacity: 0.3; }
.nf-content h2 { font-size: var(--text-2xl); margin: var(--space-4) 0 var(--space-2); }
.nf-content p { color: var(--text-secondary); margin-bottom: var(--space-6); }
</style>
