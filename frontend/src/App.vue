<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from './stores/auth'
import { useUI } from './stores/ui'
import Toasts from './components/Toasts.vue'
import QuickCreate from './components/QuickCreate.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuth()
const ui = useUI()

const bare = computed(() => route.meta.public || route.path.startsWith('/t/'))
const search = ref('')
const showCreate = ref(false)
const showUserMenu = ref(false)

onMounted(() => {
  ui.applyTheme()
  window
    .matchMedia('(prefers-color-scheme: dark)')
    .addEventListener('change', () => ui.applyTheme())
})

function doSearch() {
  router.push({ path: '/items', query: search.value ? { q: search.value } : {} })
}

const nav = [
  { to: '/', icon: '🏠', label: 'Dashboard' },
  { to: '/items', icon: '📦', label: 'Items' },
  { to: '/bins', icon: '🗃️', label: 'Bins' },
  { to: '/locations', icon: '📍', label: 'Locations' },
  { to: '/labels', icon: '🏷️', label: 'Labels' },
  { to: '/maintenance', icon: '🔧', label: 'Maintenance' },
]
</script>

<template>
  <template v-if="!bare">
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <span class="logo">📦</span> Shelfie
        </div>
        <router-link v-for="n in nav" :key="n.to" :to="n.to" class="nav-link">
          <span class="ico">{{ n.icon }}</span> {{ n.label }}
        </router-link>
        <div class="section-label">Utilities</div>
        <router-link to="/scan" class="nav-link"><span class="ico">📷</span> Scan QR</router-link>
        <router-link to="/tools" class="nav-link"><span class="ico">🛠️</span> Tools</router-link>
        <div class="spacer"></div>
        <div class="nav-link" style="cursor:default">
          <span class="ico">👤</span>
          <span class="muted" style="font-size:0.85rem">{{ auth.user?.name || 'Local' }}</span>
        </div>
      </aside>

      <div class="main">
        <header class="topbar">
          <div class="search">
            <span class="search-ico">🔍</span>
            <input v-model="search" placeholder="Search items…"
                   @keyup.enter="doSearch" />
          </div>
          <div class="grow"></div>
          <button @click="showCreate = true">＋ Create</button>
          <button class="secondary icon-btn" title="Scan QR" @click="router.push('/scan')">📷</button>
          <button class="secondary icon-btn" title="Toggle theme" @click="ui.toggleTheme()">🌓</button>
          <div v-if="!auth.authDisabled" class="dropdown">
            <button class="secondary icon-btn" @click="showUserMenu = !showUserMenu">👤</button>
            <div v-if="showUserMenu" class="dropdown-menu" @click="showUserMenu = false">
              <button @click="auth.logout()">Sign out</button>
            </div>
          </div>
        </header>

        <div class="content">
          <router-view />
        </div>
      </div>
    </div>

    <QuickCreate v-if="showCreate" @close="showCreate = false" />
    <Toasts />
  </template>

  <template v-else>
    <router-view />
    <Toasts />
  </template>
</template>
