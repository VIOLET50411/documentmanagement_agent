import { defineStore } from "pinia"
import { ref } from "vue"

const THEME_KEY = "docmind_theme"
type ThemeMode = "light" | "dark"

function applyTheme(mode: ThemeMode) {
  const root = document.documentElement
  const body = document.body
  root.classList.toggle("theme-dark", mode === "dark")
  body.classList.toggle("theme-dark", mode === "dark")
  root.style.colorScheme = mode
}

export const useThemeStore = defineStore("theme", () => {
  const isDark = ref(localStorage.getItem(THEME_KEY) === "dark")
  applyTheme(isDark.value ? "dark" : "light")

  function toggle() {
    setTheme(isDark.value ? "light" : "dark")
  }

  function setTheme(mode: ThemeMode) {
    isDark.value = mode === "dark"
    localStorage.setItem(THEME_KEY, mode)
    applyTheme(mode)
  }

  return { isDark, toggle, setTheme }
})
