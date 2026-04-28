<template>
  <div id="docmind-app" :class="{ 'theme-dark': isDark }">
    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)
</script>

<style>
/* App-level styles are handled by index.css */
</style>
