import { nextTick } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuth } from './stores/auth'
import { useUI } from './stores/ui'

import Dashboard from './views/Dashboard.vue'
import Items from './views/Items.vue'
import ItemDetail from './views/ItemDetail.vue'
import Bins from './views/Bins.vue'
import BinDetail from './views/BinDetail.vue'
import Locations from './views/Locations.vue'
import Login from './views/Login.vue'
import NotFound from './views/NotFound.vue'

const routes = [
  { path: '/', component: Dashboard, meta: { title: 'Dashboard' } },
  { path: '/items', component: Items, meta: { title: 'Items' } },
  { path: '/items/:id', component: ItemDetail, meta: { title: 'Item' } },
  { path: '/bins', component: Bins, meta: { title: 'Bins' } },
  { path: '/bins/:id', component: BinDetail, meta: { title: 'Bin' } },
  { path: '/locations', component: Locations, meta: { title: 'Locations' } },
  { path: '/locations/:id', component: () => import('./views/LocationDetail.vue'), meta: { title: 'Location' } },
  { path: '/labels', component: () => import('./views/Labels.vue'), meta: { title: 'Labels' } },
  { path: '/labels/print', component: () => import('./views/LabelSheet.vue'), meta: { title: 'Print labels' } },
  { path: '/maintenance', component: () => import('./views/Maintenance.vue'), meta: { title: 'Maintenance' } },
  { path: '/checkouts', component: () => import('./views/Checkouts.vue'), meta: { title: 'Checked out' } },
  { path: '/restock', component: () => import('./views/Restock.vue'), meta: { title: 'Restock' } },
  { path: '/duplicates', component: () => import('./views/Duplicates.vue'), meta: { title: 'Duplicates' } },
  { path: '/review', component: () => import('./views/Review.vue'), meta: { title: 'Review' } },
  { path: '/tools', component: () => import('./views/Tools.vue'), meta: { title: 'Tools' } },
  { path: '/database', component: () => import('./views/Database.vue'), meta: { title: 'Database' } },
  { path: '/report', component: () => import('./views/Report.vue'), meta: { title: 'Report' } },
  { path: '/home-assistant', component: () => import('./views/HomeAssistant.vue'), meta: { title: 'Home Assistant' } },
  { path: '/scan', component: () => import('./views/ScanLaunch.vue'), meta: { title: 'Scan' } },
  { path: '/t/:token', component: () => import('./views/Scan.vue'), meta: { public: false, title: 'Scan result' } },
  { path: '/login', component: Login, meta: { public: true, title: 'Sign in' } },
  // Must stay last: anything unmatched lands on a real page, not a blank shell.
  { path: '/:pathMatch(.*)*', component: NotFound, meta: { title: 'Not found' } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
  // Back/forward restores the old position; a new page starts at the top. A
  // query-only change (list filters, paging) keeps the scroll where it is.
  scrollBehavior(to, from, saved) {
    if (saved) return saved
    if (to.path === from.path) return false
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.ready) await auth.bootstrap()
  // Remember where the user was going; Login.vue returns there (via safeRedirect).
  if (!to.meta.public && !auth.isAuthed) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.path === '/login' && auth.isAuthed) return '/'
})

// Announce the new page: title for the tab/history, and focus the page heading
// so screen-reader and keyboard users start on the new content rather than on
// the link they activated. The tabindex is set here, once, not in every view.
router.afterEach((to, from, failure) => {
  if (failure) return
  document.title = (to.meta.title ? to.meta.title + ' · ' : '') + 'HomeHoard'
  if (to.path === from.path) return
  // An error toast is about the page being left; don't carry it to the next.
  useUI().clearErrorToasts()
  // Initial load: the browser already starts at the top of the document.
  if (!from.matched.length) return
  nextTick(() => {
    const h1 = document.querySelector('main h1')
    if (!h1) return
    h1.setAttribute('tabindex', '-1')
    h1.focus({ preventScroll: true })
  })
})

export default router
