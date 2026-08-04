<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router"
import {
  IconAdjustments,
  IconFolders,
  IconGauge,
  IconLayoutList,
  IconLogout,
  IconMoon,
  IconMovie,
  IconPlus,
  IconSun,
  IconUsers,
} from "@tabler/icons-vue"
import { api, auth } from "./api"

const route = useRoute()
const router = useRouter()
const theme = ref(localStorage.getItem("h3-theme") || "system")
const isPublic = computed(() => Boolean(route.meta.public))

const userLinks = [
  { to: "/create", label: "新建", icon: IconPlus },
  { to: "/jobs", label: "我的任务", icon: IconMovie },
  { to: "/assets", label: "素材库", icon: IconFolders },
]
const adminLinks = [
  { to: "/admin/queue", label: "总队列", icon: IconLayoutList },
  { to: "/admin/users", label: "用户", icon: IconUsers },
  { to: "/admin/system", label: "系统", icon: IconGauge },
]

function applyTheme(): void {
  if (theme.value === "system") document.documentElement.removeAttribute("data-theme")
  else document.documentElement.dataset.theme = theme.value
  localStorage.setItem("h3-theme", theme.value)
}

function cycleTheme(): void {
  theme.value = theme.value === "system" ? "dark" : theme.value === "dark" ? "light" : "system"
}

async function logout(): Promise<void> {
  await api("/api/auth/logout", { method: "POST" })
  auth.user = null
  auth.csrf = ""
  await router.push("/login")
}

watch(theme, applyTheme)
onMounted(applyTheme)
</script>

<template>
  <RouterView v-if="isPublic || !auth.user" />
  <div v-else class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/create">
        <span class="brand-mark">H3</span>
        <span>MiniMax</span>
      </RouterLink>

      <nav class="nav-group" aria-label="工作区">
        <RouterLink v-for="item in userLinks" :key="item.to" :to="item.to" class="nav-link">
          <component :is="item.icon" :size="20" :stroke-width="1.8" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <nav v-if="auth.user.is_admin" class="nav-group admin-nav" aria-label="管理">
        <span class="nav-heading">管理</span>
        <RouterLink v-for="item in adminLinks" :key="item.to" :to="item.to" class="nav-link">
          <component :is="item.icon" :size="20" :stroke-width="1.8" />
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-bottom">
        <button class="nav-link button-link" type="button" @click="cycleTheme">
          <IconMoon v-if="theme === 'dark'" :size="20" />
          <IconSun v-else-if="theme === 'light'" :size="20" />
          <IconAdjustments v-else :size="20" />
          <span>{{ theme === "dark" ? "深色" : theme === "light" ? "浅色" : "跟随系统" }}</span>
        </button>
        <button class="nav-link button-link" type="button" @click="logout">
          <IconLogout :size="20" />
          <span>退出</span>
        </button>
        <div class="account-block">
          <span class="account-avatar">{{ auth.user.username.slice(0, 1).toUpperCase() }}</span>
          <span class="account-name">{{ auth.user.username }}</span>
          <span class="weight-chip">{{ auth.user.weight }}</span>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <RouterView />
    </main>
  </div>
</template>
