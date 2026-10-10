import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useUI } from './stores/ui'
import { installErrorLog } from './utils/errorLog'
import { migrateLegacyKeys } from './storageKeys'
import './style.css'

// Rename pre-HomeHoard storage keys before anything reads storage.
migrateLegacyKeys()

// Capture client-side errors early so a later bug report can include them.
installErrorLog()

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

// Apply the saved theme before mount to avoid a flash of the wrong theme.
useUI(pinia).applyTheme()

app.use(router)
app.mount('#app')
