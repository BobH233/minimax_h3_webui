<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { IconMovie, IconPlus } from "@tabler/icons-vue"
import { api, type Job, type JobStatus } from "../api"
import JobCard from "../components/JobCard.vue"

const jobs = ref<Job[]>([])
const loading = ref(true)
const error = ref("")
const filter = ref<"all" | JobStatus>("all")
let timer = 0

const filtered = computed(() => filter.value === "all" ? jobs.value : jobs.value.filter((job) => job.status === filter.value))
const filters: Array<{ key: "all" | JobStatus; label: string }> = [
  { key: "all", label: "全部" },
  { key: "queued", label: "排队中" },
  { key: "generating", label: "生成中" },
  { key: "succeeded", label: "已完成" },
  { key: "failed", label: "失败" },
]

async function load(silent = false): Promise<void> {
  if (!silent) loading.value = true
  try {
    jobs.value = await api<Job[]>("/api/jobs")
    error.value = ""
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载失败"
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(() => void load(true), 3000)
})
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
        <button v-for="item in filters" :key="item.key" type="button" :class="{ active: filter === item.key }" @click="filter = item.key">{{ item.label }}</button>
      </div>
      <span>{{ filtered.length }} 个任务</span>
    </div>
    <p v-if="error" class="form-error page-error">{{ error }}</p>
    <div v-if="loading" class="skeleton-list"><div v-for="item in 5" :key="item" class="skeleton-row" /></div>
    <div v-else-if="filtered.length" class="job-list"><JobCard v-for="job in filtered" :key="job.id" :job="job" /></div>
    <section v-else class="empty-state"><IconMovie :size="34" :stroke-width="1.5" /><h2>还没有任务</h2><RouterLink to="/create">创建第一个视频</RouterLink></section>
  </div>
</template>
