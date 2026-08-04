import { createRouter, createWebHistory } from "vue-router"
import { auth, initializeAuth } from "./api"
import AssetsView from "./views/AssetsView.vue"
import CreateView from "./views/CreateView.vue"
import JobDetailView from "./views/JobDetailView.vue"
import JobsView from "./views/JobsView.vue"
import LoginView from "./views/LoginView.vue"
import PublicShareView from "./views/PublicShareView.vue"
import SetupView from "./views/SetupView.vue"
import AdminQueueView from "./views/admin/AdminQueueView.vue"
import AdminSystemView from "./views/admin/AdminSystemView.vue"
import AdminUsersView from "./views/admin/AdminUsersView.vue"

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/create" },
    { path: "/setup", component: SetupView, meta: { public: true } },
    { path: "/login", component: LoginView, meta: { public: true } },
    { path: "/share/:token", component: PublicShareView, meta: { public: true } },
    { path: "/create", component: CreateView },
    { path: "/jobs", component: JobsView },
    { path: "/jobs/:id", component: JobDetailView },
    { path: "/assets", component: AssetsView },
    { path: "/admin/users", component: AdminUsersView, meta: { admin: true } },
    { path: "/admin/queue", component: AdminQueueView, meta: { admin: true } },
    { path: "/admin/system", component: AdminSystemView, meta: { admin: true } },
    { path: "/:pathMatch(.*)*", redirect: "/create" },
  ],
})

router.beforeEach(async (to) => {
  if (!auth.initialized) await initializeAuth()
  if (auth.needsSetup && to.path !== "/setup") return "/setup"
  if (!auth.needsSetup && to.path === "/setup") return auth.user ? "/create" : "/login"
  if (!auth.user && !to.meta.public) return "/login"
  if (auth.user && to.path === "/login") return "/create"
  if (to.meta.admin && !auth.user?.is_admin) return "/create"
  return true
})

export default router
