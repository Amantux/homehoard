import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuth } from './stores/auth'

import Dashboard from './views/Dashboard.vue'
import Items from './views/Items.vue'
import ItemDetail from './views/ItemDetail.vue'
import Bins from './views/Bins.vue'
import BinDetail from './views/BinDetail.vue'
import Locations from './views/Locations.vue'
import LocationDetail from './views/LocationDetail.vue'
import Labels from './views/Labels.vue'
import Maintenance from './views/Maintenance.vue'
import Tools from './views/Tools.vue'
import Scan from './views/Scan.vue'
import Login from './views/Login.vue'

const routes = [
  { path: '/', component: Dashboard },
  { path: '/items', component: Items },
  { path: '/items/:id', component: ItemDetail },
  { path: '/bins', component: Bins },
  { path: '/bins/:id', component: BinDetail },
  { path: '/locations', component: Locations },
  { path: '/locations/:id', component: LocationDetail },
  { path: '/labels', component: Labels },
  { path: '/maintenance', component: Maintenance },
  { path: '/tools', component: Tools },
  { path: '/t/:token', component: Scan, meta: { public: false } },
  { path: '/login', component: Login, meta: { public: true } },
]

const router = createRouter({ history: createWebHashHistory(), routes })

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (!auth.ready) await auth.bootstrap()
  if (!to.meta.public && !auth.isAuthed) return '/login'
  if (to.path === '/login' && auth.isAuthed) return '/'
})

export default router
