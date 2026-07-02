import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useUI } from './stores/ui'
import './style.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// Apply the saved theme before mount to avoid a flash of the wrong theme.
useUI(pinia).applyTheme()

app.use(router)
app.mount('#app')
