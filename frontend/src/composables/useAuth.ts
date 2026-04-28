import { computed } from "vue"
import { useAuthStore } from "@/stores/auth"

export function useAuth() {
  const authStore = useAuthStore()

  return {
    authStore,
    user: computed(() => authStore.user),
    isAuthenticated: computed(() => authStore.isAuthenticated),
    isAdmin: computed(() => authStore.user?.role === "ADMIN"),
    login: authStore.login,
    logout: authStore.logout,
    hydrateUser: authStore.hydrateUser,
  }
}
