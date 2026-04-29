<template>
  <div id="docmind-app" :class="{ 'theme-dark': isDark, 'native-app': nativeApp }">
    <router-view />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { isNativeApp } from '@/mobile/capacitor'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)
const nativeApp = isNativeApp()
</script>

<style>
/* App-level styles are handled by index.css */
</style>
