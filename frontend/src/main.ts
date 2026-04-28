import { createApp } from "vue"
import { createPinia } from "pinia"
import router from "./router"
import App from "./App.vue"
import "./assets/css/index.css"
import { useAuthStore } from "@/stores/auth"

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

const authStore = useAuthStore(pinia)
authStore.hydrateUser()

app.mount("#app")
