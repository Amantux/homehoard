import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuth } from './stores/auth'

import Dashboard from './views/Dashboard.vue'
import Items from './views/Items.vue'
import ItemDetail from './views/ItemDetail.vue'
import Bins from './views/Bins.vue'
import BinDetail from './views/BinDetail.vue'
import Locations from './views/Locations.vue'
import ScanLaunch from './views/ScanLaunch.vue'
import Login from './views/Login.vue'
import NotFound from './views/NotFound.vue'

const routes = [
  { path: '/', component: Dashboard },
  { path: '/items', component: Items },
  { path: '/items/:id', component: ItemDetail },
  { path: '/bins', component: Bins },
  { path: '/bins/:id', component: BinDetail },
  { path: '/locations', component: Locations },
  { path: '/locations/:id', component: () => import('./views/LocationDetail.vue') },
  { path: '/labels', component: () => import('./views/Labels.vue') },
  { path: '/labels/print', component: () => import('./views/LabelSheet.vue') },
  { path: '/maintenance', component: () => import('./views/Maintenance.vue') },
  { path: '/checkouts', component: () => import('./views/Checkouts.vue') },
  { path: '/restock', component: () => import('./views/Restock.vue') },
  { path: '/duplicates', component: () => import('./views/Duplicates.vue') },
  { path: '/review', component: () => import('./views/Review.vue') },
  { path: '/tools', component: () => import('./views/Tools.vue') },
  { path: '/database', component: () => import('./views/Database.vue') },
  { path: '/report', component: () => import('./views/Report.vue') },
  { path: '/home-assistant', component: () => import('./views/HomeAssistant.vue') },
  { path: '/scan', component: ScanLaunch },
  { path: '/t/:token', component: () => import('./views/Scan.vue'), meta: { public: false } },
  { path: '/login', component: Login, meta: { public: true } },
  // Must stay last: anything unmatched lands on a real page, not a blank shell.
  { path: '/:pathMatch(.*)*', component: NotFound },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.ready) await auth.bootstrap()
  // Remember where the user was going; Login.vue returns there (via safeRedirect).
  if (!to.meta.public && !auth.isAuthed) return { path: '/login', query: { redirect: to.fullPath } }
  if (to.path === '/login' && auth.isAuthed) return '/'
})

export default router
