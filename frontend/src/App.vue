<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from './stores/auth'
import { useUI } from './stores/ui'
import Toasts from './components/Toasts.vue'
import QuickCreate from './components/QuickCreate.vue'
import ScannerModal from './components/ScannerModal.vue'
import SearchModal from './components/SearchModal.vue'
import ReportBug from './components/ReportBug.vue'
import ChatAssistant from './components/ChatAssistant.vue'

const route = useRoute()
const auth = useAuth()
const ui = useUI()

const bare = computed(() => route.meta.public || route.path.startsWith('/t/'))
const showCreate = ref(false)
const showScanner = ref(false)
const showSearch = ref(false)
const showUserMenu = ref(false)
const showReport = ref(false)

// Mobile nav drawer. The sidebar is off-canvas below 720px; this toggles it.
// Previously the sidebar was simply display:none there, so no page except the
// dashboard was reachable on a phone.
const menuOpen = ref(false)
// Close the drawer whenever the route changes (i.e. a nav link was tapped).
watch(() => route.fullPath, () => { menuOpen.value = false })

onMounted(() => {
  ui.applyTheme()
  window
    .matchMedia('(prefers-color-scheme: dark)')
    .addEventListener('change', () => ui.applyTheme())
  // Press "/" anywhere to open search.
  window.addEventListener('keydown', (e) => {
    if (e.key === '/' && !/input|textarea|select/i.test(e.target.tagName)) {
      e.preventDefault()
      showSearch.value = true
    }
  })
})

const nav = [
  { to: '/', icon: '🏠', label: 'Dashboard' },
  { to: '/items', icon: '📦', label: 'Items' },
  { to: '/bins', icon: '🗃️', label: 'Bins' },
  { to: '/locations', icon: '📍', label: 'Locations' },
  { to: '/labels', icon: '🏷️', label: 'Labels' },
  { to: '/maintenance', icon: '🔧', label: 'Maintenance' },
  { to: '/checkouts', icon: '📤', label: 'Checked out' },
]
</script>

<template>
  <template v-if="!bare">
    <div class="app-shell">
      <!-- Scrim behind the mobile drawer; tap to close. -->
      <div v-if="menuOpen" class="nav-scrim only-mobile" @click="menuOpen = false"></div>
      <aside class="sidebar" :class="{ 'mobile-open': menuOpen }">
        <div class="brand">
          <span class="logo">📦</span> HomeHoard
        </div>
        <router-link v-for="n in nav" :key="n.to" :to="n.to" class="nav-link">
          <span class="ico">{{ n.icon }}</span> {{ n.label }}
        </router-link>
        <div class="section-label">Utilities</div>
        <a href="#" class="nav-link" @click.prevent="showScanner = true"><span class="ico">📷</span> Scan QR</a>
        <router-link to="/home-assistant" class="nav-link"><span class="ico">🔌</span> Home Assistant</router-link>
        <router-link to="/tools" class="nav-link"><span class="ico">🛠️</span> Tools</router-link>
        <router-link to="/review" class="nav-link"><span class="ico">🗂️</span> Review</router-link>
        <router-link to="/database" class="nav-link"><span class="ico">🗄️</span> Database</router-link>
        <router-link to="/report" class="nav-link"><span class="ico">📄</span> Report</router-link>
        <div class="spacer"></div>
        <div class="nav-link" style="cursor:default">
          <span class="ico">👤</span>
          <span class="muted" style="font-size:0.85rem">{{ auth.user?.name || 'Local' }}</span>
        </div>
      </aside>

      <div class="main">
        <header class="topbar">
          <button
            class="secondary icon-btn only-mobile"
            aria-label="Open menu"
            @click="menuOpen = true"
          >☰</button>
          <div class="search" @click="showSearch = true">
            <span class="search-ico">🔍</span>
            <input placeholder="Find where something is…  ( / )" readonly
                   style="cursor:pointer" @focus="showSearch = true" />
          </div>
          <div class="grow"></div>
          <button @click="showCreate = true">＋ Create</button>
          <button class="secondary icon-btn" title="Scan QR" @click="showScanner = true">📷</button>
          <button class="secondary icon-btn" title="Report a bug" aria-label="Report a bug"
                  @click="showReport = true">🐞</button>
          <button class="secondary icon-btn" title="Toggle theme" @click="ui.toggleTheme()">🌓</button>
          <div v-if="!auth.authDisabled" class="dropdown">
            <button class="secondary icon-btn" @click="showUserMenu = !showUserMenu">👤</button>
            <div v-if="showUserMenu" class="dropdown-menu" @click="showUserMenu = false">
              <button @click="auth.logout()">Sign out</button>
            </div>
          </div>
        </header>

        <div class="content">
          <!-- Key by path so navigating between two of the same route (e.g. item→item
               from search) remounts the view and loads the new record, instead of
               reusing the component and appearing stuck on the previous one. -->
          <router-view :key="$route.path" />
        </div>
      </div>
    </div>

    <QuickCreate v-if="showCreate || ui.createKind" :initial-kind="ui.createKind || 'item'"
                 @close="showCreate = false; ui.closeCreate()" />
    <ScannerModal v-if="showScanner" @close="showScanner = false" />
    <SearchModal v-if="showSearch" @close="showSearch = false" />
    <ReportBug v-if="showReport || ui.bugReport" :initial="ui.bugReport"
               @close="showReport = false; ui.closeBugReport()" />
    <ChatAssistant />
    <Toasts />
  </template>

  <template v-else>
    <router-view />
    <Toasts />
  </template>
</template>
