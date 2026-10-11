<script setup>
import { ref, computed, onMounted, watch, nextTick, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from './stores/auth'
import { useUI } from './stores/ui'
import { api, setWriteHook, setUnauthorizedHook } from './api'
import Toasts from './components/Toasts.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import { prefetchZxing } from './components/zxingPrefetch'
import ChatAssistant from './components/ChatAssistant.vue'

// Modals are only mounted on demand, so they load on demand too and stay out
// of the main chunk. prefetchZxing comes from its own module for the same
// reason: importing it from ScannerModal.vue would pull the modal back in.
const QuickCreate = defineAsyncComponent(() => import('./components/QuickCreate.vue'))
const ScannerModal = defineAsyncComponent(() => import('./components/ScannerModal.vue'))
const SearchModal = defineAsyncComponent(() => import('./components/SearchModal.vue'))
const ReportBug = defineAsyncComponent(() => import('./components/ReportBug.vue'))
const ChangePasswordModal = defineAsyncComponent(() => import('./components/ChangePasswordModal.vue'))
const route = useRoute()
const auth = useAuth()
const ui = useUI()

const bare = computed(() => route.meta.public || route.path.startsWith('/t/'))
const showCreate = ref(false)
const showScanner = ref(false)
const showSearch = ref(false)
const showUserMenu = ref(false)
const showReport = ref(false)
const showChangePassword = ref(false)

// Account menu: Esc closes and returns focus to the toggle; a click or tap
// anywhere outside closes it without moving focus.
const userMenuWrap = ref(null)
const userMenuToggle = ref(null)
function toggleUserMenu() {
  showUserMenu.value = !showUserMenu.value
  if (showUserMenu.value) nextTick(() => userMenuWrap.value?.querySelector('[role="menuitem"]')?.focus())
}
function closeUserMenu(returnFocus) {
  if (!showUserMenu.value) return
  showUserMenu.value = false
  if (returnFocus) userMenuToggle.value?.focus()
}

// Mobile nav drawer. The sidebar is off-canvas below 720px; this toggles it.
// Previously the sidebar was simply display:none there, so no page except the
// dashboard was reachable on a phone.
const menuOpen = ref(false)
// Start the live-sync poller the moment a login lands (startLiveSync is
// idempotent, so a hot-reload or double-fire is harmless); stop it on logout.
watch(() => auth.isAuthed, (ok) => { if (ok) ui.startLiveSync(api); else ui.stopLiveSync() })
// Any successful local write refreshes the open views immediately.
setWriteHook(() => ui.dataChanged())
// A 401 ends the session in place: no navigation, so the open view and any
// unsaved input stay put; a banner offers sign-in and returns here afterwards.
// expire() is false when there was no signed-in session (login form, bootstrap,
// auth disabled), so those 401s raise no banner.
setUnauthorizedHook(() => {
  if (!auth.expire()) return
  ui.stopLiveSync()
  ui.sessionExpired = true
})
const showExpired = computed(() => ui.sessionExpired && !route.meta.public)

// Close the drawer whenever the route changes (i.e. a nav link was tapped).
watch(() => route.fullPath, () => { menuOpen.value = false })

onMounted(() => {
  ui.applyTheme()
  // Live sync: only when authenticated — the poller would just 401 on the
  // login screen (auth store logs the user in via a route change, and the
  // watcher below starts it then).
  if (auth.isAuthed) ui.startLiveSync(api)
  window
    .matchMedia('(prefers-color-scheme: dark)')
    .addEventListener('change', () => ui.applyTheme())
  document.addEventListener('pointerdown', (e) => {
    if (showUserMenu.value && !userMenuWrap.value?.contains(e.target)) closeUserMenu(false)
  })
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
  { to: '/restock', icon: '🛒', label: 'Restock' },
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
        <router-link to="/duplicates" class="nav-link"><span class="ico">⧉</span> Duplicates</router-link>
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
            <input aria-label="Find where something is" placeholder="Find where something is…  ( / )" readonly
                   style="cursor:pointer" @focus="showSearch = true" />
          </div>
          <div class="grow"></div>
          <button @click="showCreate = true">＋ Create</button>
          <button aria-label="Scan QR" class="secondary icon-btn" title="Scan QR" @pointerenter="prefetchZxing" @focus="prefetchZxing" @click="showScanner = true">📷</button>
          <button class="secondary icon-btn" title="Report a bug" aria-label="Report a bug"
                  @click="showReport = true">🐞</button>
          <button aria-label="Toggle theme" class="secondary icon-btn" title="Toggle theme" @click="ui.toggleTheme()">🌓</button>
          <div v-if="!auth.authDisabled" ref="userMenuWrap" class="dropdown"
               @keydown.esc="closeUserMenu(true)">
            <button ref="userMenuToggle" aria-label="Account menu" class="secondary icon-btn"
                    aria-haspopup="menu" :aria-expanded="showUserMenu ? 'true' : 'false'"
                    aria-controls="user-menu" @click="toggleUserMenu">👤</button>
            <div v-if="showUserMenu" id="user-menu" class="dropdown-menu" role="menu" @click="showUserMenu = false">
              <!-- Password users only: HA-linked users have no password here. -->
              <button v-if="auth.user && auth.user.ha === false" role="menuitem"
                      @click="showChangePassword = true">Change password…</button>
              <button role="menuitem" @click="auth.logout()">Sign out</button>
            </div>
          </div>
        </header>

        <main class="content">
          <!-- Key by path so navigating between two of the same route (e.g. item→item
               from search) remounts the view and loads the new record, instead of
               reusing the component and appearing stuck on the previous one. -->
          <div v-if="showExpired" class="session-banner" role="alert">
            Your session ended.
            <router-link :to="{ path: '/login', query: { redirect: route.fullPath } }">Sign in again</router-link>
          </div>
          <router-view :key="$route.path" />
        </main>
      </div>
    </div>

    <QuickCreate v-if="showCreate || ui.createKind" :initial-kind="ui.createKind || 'item'"
                 @close="showCreate = false; ui.closeCreate()" />
    <ScannerModal v-if="showScanner" @close="showScanner = false" />
    <SearchModal v-if="showSearch" @close="showSearch = false" />
    <ReportBug v-if="showReport || ui.bugReport" :initial="ui.bugReport"
               @close="showReport = false; ui.closeBugReport()" />
    <!-- The menu item that opened it is gone by now, so hand focus back to the toggle. -->
    <ChangePasswordModal v-if="showChangePassword"
                         @close="showChangePassword = false; userMenuToggle?.focus()" />
    <ChatAssistant />
    <Toasts />
    <ConfirmDialog />
  </template>

  <template v-else>
    <div v-if="showExpired" class="session-banner" role="alert">
      Your session ended.
      <router-link :to="{ path: '/login', query: { redirect: route.fullPath } }">Sign in again</router-link>
    </div>
    <main><router-view /></main>
    <Toasts />
  </template>
</template>

<style>
/* Persistent (never auto-dismissed) notice that a 401 ended the session; the
   view below stays mounted so unsaved input is not lost. */
.session-banner {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 16px; padding: 10px 14px;
  background: var(--surface-2); border: 1px solid var(--border);
  border-left: 3px solid var(--warning); border-radius: var(--radius);
}
.session-banner a { font-weight: 600; }
</style>
