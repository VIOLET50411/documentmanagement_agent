import { defineStore } from "pinia"
import { ref } from "vue"

const THEME_KEY = "docmind_theme"
type ThemeMode = "light" | "dark"

export const useThemeStore = defineStore("theme", () => {
  const isDark = ref(localStorage.getItem(THEME_KEY) === "dark")

  function toggle() {
    setTheme(isDark.value ? "light" : "dark")
  }

  function setTheme(mode: ThemeMode) {
    isDark.value = mode === "dark"
    localStorage.setItem(THEME_KEY, mode)
  }

  return { isDark, toggle, setTheme }
})
