<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { IconMovie, IconPlus } from "@tabler/icons-vue"
import { api, type Job, type JobStatus, type PaginatedResponse } from "../api"
import JobCard from "../components/JobCard.vue"
import PaginationNav from "../components/PaginationNav.vue"

const route = useRoute()
const router = useRouter()
const jobs = ref<Job[]>([])
const loading = ref(true)
const error = ref("")
const total = ref(0)
const totalPages = ref(1)
let timer = 0

const filters: Array<{ key: "all" | JobStatus; label: string }> = [
  { key: "all", label: "全部" },
  { key: "queued", label: "排队中" },
  { key: "generating", label: "生成中" },
  { key: "succeeded", label: "已完成" },
  { key: "failed", label: "失败" },
]
const filterKeys = new Set(filters.map((item) => item.key))
const page = computed(() => {
  const value = Number(route.query.page)
  return Number.isInteger(value) && value > 0 ? value : 1
})
const filter = computed<"all" | JobStatus>(() => {
  const value = typeof route.query.status === "string" ? route.query.status : "all"
  return filterKeys.has(value as "all" | JobStatus) ? value as "all" | JobStatus : "all"
})

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const params = new URLSearchParams({ page: String(page.value) })
    if (filter.value !== "all") params.set("status", filter.value)
    const result = await api<PaginatedResponse<Job>>(`/api/jobs?${params}`)
    jobs.value = result.items
    total.value = result.total
    totalPages.value = result.total_pages
    error.value = ""
    if (result.page !== page.value) {
      await router.replace({ query: { ...route.query, page: String(result.page) } })
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载失败"
  } finally {
    loading.value = false
  }
}

async function loadRoute(): Promise<void> {
  const status = filter.value === "all" ? undefined : filter.value
  if (route.query.page !== String(page.value) || route.query.status !== status) {
    await router.replace({ query: { ...route.query, page: String(page.value), status } })
    return
  }
  await load()
}

function setFilter(value: "all" | JobStatus): void {
  void router.push({ query: { ...route.query, page: "1", status: value === "all" ? undefined : value } })
}

function setPage(value: number): void {
  void router.push({ query: { ...route.query, page: String(value) } })
}

watch(() => [route.query.page, route.query.status], () => void loadRoute(), { immediate: true })
onMounted(() => { timer = window.setInterval(() => void load(true), 3000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div><h1>我的任务</h1><p>查看排队、生成和历史结果。</p></div>
      <RouterLink class="primary-button" to="/create"><IconPlus :size="18" />新建视频</RouterLink>
    </header>
    <div class="toolbar">
      <div class="filter-tabs">
        <button v-for="item in filters" :key="item.key" type="button" :class="{ active: filter === item.key }" @click="setFilter(item.key)">{{ item.label }}</button>
      </div>
      <span>{{ total }} 个任务</span>
    </div>
    <p v-if="error" class="form-error page-error">{{ error }}</p>
    <div v-if="loading" class="skeleton-list"><div v-for="item in 5" :key="item" class="skeleton-row" /></div>
    <div v-else-if="jobs.length" class="job-list"><JobCard v-for="job in jobs" :key="job.id" :job="job" /></div>
    <section v-else class="empty-state"><IconMovie :size="34" :stroke-width="1.5" /><h2>还没有任务</h2><RouterLink to="/create">创建第一个视频</RouterLink></section>
    <PaginationNav :page="page" :total-pages="totalPages" @change="setPage" />
  </div>
</template>
