<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { IconTrash } from "@tabler/icons-vue"
import { api, type Job } from "../../api"
import JobCard from "../../components/JobCard.vue"

const jobs = ref<Job[]>([])
const error = ref("")
let timer = 0
const active = computed(() => jobs.value.filter((job) => ["submitting", "generating"].includes(job.status)))
const queued = computed(() => jobs.value.filter((job) => job.status === "queued"))
const history = computed(() => jobs.value.filter((job) => !["submitting", "generating", "queued"].includes(job.status)))

async function load(): Promise<void> {
  try {
    jobs.value = await api<Job[]>("/api/admin/queue")
    error.value = ""
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载失败"
  }
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

onMounted(() => {
  void load()
  timer = window.setInterval(() => void load(), 3000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <header class="page-header"><div><h1>总队列</h1><p>按当前用户权重实时排序。</p></div><div class="queue-summary"><strong>{{ queued.length }}</strong><span>等待</span><strong>{{ active.length }}</strong><span>执行中</span></div></header>
    <p v-if="error" class="form-error page-error">{{ error }}</p>
    <section v-if="active.length" class="queue-group"><div class="section-heading"><h2>正在执行</h2><span>{{ active.length }}</span></div><div class="job-list"><JobCard v-for="job in active" :key="job.id" :job="job" /></div></section>
    <section class="queue-group"><div class="section-heading"><h2>等待队列</h2><span>{{ queued.length }}</span></div><div v-if="queued.length" class="admin-job-list"><div v-for="(job, index) in queued" :key="job.id" class="admin-job-row"><span class="queue-rank">{{ index + 1 }}</span><JobCard :job="job" /><button class="icon-button danger-icon" type="button" aria-label="删除任务" @click="remove(job)"><IconTrash :size="18" /></button></div></div><div v-else class="empty-inline">当前没有等待任务</div></section>
    <section v-if="history.length" class="queue-group"><div class="section-heading"><h2>最近任务</h2><span>{{ history.length }}</span></div><div class="admin-job-list history-list"><div v-for="job in history" :key="job.id" class="admin-job-row"><JobCard :job="job" /><button class="icon-button danger-icon" type="button" aria-label="删除任务" @click="remove(job)"><IconTrash :size="18" /></button></div></div></section>
  </div>
</template>
