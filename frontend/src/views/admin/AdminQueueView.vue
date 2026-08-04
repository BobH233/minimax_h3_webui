<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { IconTrash } from "@tabler/icons-vue"
import { api, type AdminQueueResponse, type Job } from "../../api"
import JobCard from "../../components/JobCard.vue"
import PaginationNav from "../../components/PaginationNav.vue"

const route = useRoute()
const router = useRouter()
const jobs = ref<Job[]>([])
const error = ref("")
const loading = ref(true)
const totalPages = ref(1)
const statusCounts = ref<Record<string, number>>({})
let timer = 0

const page = computed(() => {
  const value = Number(route.query.page)
  return Number.isInteger(value) && value > 0 ? value : 1
})
const active = computed(() => jobs.value.filter((job) => ["submitting", "generating"].includes(job.status)))
const queued = computed(() => jobs.value.filter((job) => job.status === "queued"))
const history = computed(() => jobs.value.filter((job) => !["submitting", "generating", "queued"].includes(job.status)))
const activeTotal = computed(() => (statusCounts.value.submitting || 0) + (statusCounts.value.generating || 0))
const queuedTotal = computed(() => statusCounts.value.queued || 0)

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    const result = await api<AdminQueueResponse>(`/api/admin/queue?page=${page.value}`)
    jobs.value = result.items
    totalPages.value = result.total_pages
    statusCounts.value = result.status_counts
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
  if (route.query.page !== String(page.value)) {
    await router.replace({ query: { ...route.query, page: String(page.value) } })
    return
  }
  await load()
}

function setPage(value: number): void {
  void router.push({ query: { ...route.query, page: String(value) } })
}

function queueRank(job: Job): number {
  return Math.max(1, job.queue_ahead - activeTotal.value + 1)
}

async function remove(job: Job): Promise<void> {
  if (!window.confirm("从管理列表中删除这个任务？")) return
  try {
    await api(`/api/admin/jobs/${job.id}`, { method: "DELETE" })
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "删除失败"
  }
}

watch(() => route.query.page, () => void loadRoute(), { immediate: true })
onMounted(() => { timer = window.setInterval(() => void load(true), 3000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <header class="page-header"><div><h1>总队列</h1><p>按当前用户权重实时排序。</p></div><div class="queue-summary"><strong>{{ queuedTotal }}</strong><span>等待</span><strong>{{ activeTotal }}</strong><span>执行中</span></div></header>
    <p v-if="error" class="form-error page-error">{{ error }}</p>
    <div v-if="loading" class="skeleton-list"><div v-for="item in 5" :key="item" class="skeleton-row" /></div>
    <template v-else>
      <section v-if="active.length" class="queue-group"><div class="section-heading"><h2>正在执行</h2><span>{{ active.length }}</span></div><div class="job-list"><JobCard v-for="job in active" :key="job.id" :job="job" /></div></section>
      <section v-if="queued.length" class="queue-group"><div class="section-heading"><h2>等待队列</h2><span>{{ queued.length }}</span></div><div class="admin-job-list"><div v-for="job in queued" :key="job.id" class="admin-job-row"><span class="queue-rank">{{ queueRank(job) }}</span><JobCard :job="job" /><button class="icon-button danger-icon" type="button" aria-label="删除任务" @click="remove(job)"><IconTrash :size="18" /></button></div></div></section>
      <section v-if="history.length" class="queue-group"><div class="section-heading"><h2>历史任务</h2><span>{{ history.length }}</span></div><div class="admin-job-list history-list"><div v-for="job in history" :key="job.id" class="admin-job-row"><JobCard :job="job" /><button class="icon-button danger-icon" type="button" aria-label="删除任务" @click="remove(job)"><IconTrash :size="18" /></button></div></div></section>
      <div v-if="!jobs.length" class="empty-state compact-empty">暂无任务</div>
      <PaginationNav :page="page" :total-pages="totalPages" @change="setPage" />
    </template>
  </div>
</template>
