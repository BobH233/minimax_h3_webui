<script setup lang="ts">
import type { JobStatus } from "../api"

defineProps<{ status: JobStatus }>()

const labels: Record<JobStatus, string> = {
  queued: "排队中",
  submitting: "提交中",
  generating: "正在生成",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
}
</script>

<template>
  <span class="status-badge" :class="`status-${status}`">{{ labels[status] }}</span>
</template>
