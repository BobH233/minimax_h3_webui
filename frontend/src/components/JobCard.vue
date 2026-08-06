<script setup lang="ts">
import { IconArrowRight, IconClock } from "@tabler/icons-vue"
import { formatDate, formatDuration, type Job } from "../api"
import AssetThumb from "./AssetThumb.vue"
import PromptText from "./PromptText.vue"
import StatusBadge from "./StatusBadge.vue"

defineProps<{ job: Job }>()
</script>

<template>
  <RouterLink class="job-row" :to="`/jobs/${job.id}`">
    <div class="job-row-main">
      <div class="job-row-top">
        <StatusBadge :status="job.status" />
        <span v-if="job.user" class="job-user">{{ job.user.username }}</span>
        <span v-if="job.user" class="weight-chip">{{ job.user.weight }}</span>
        <span class="job-time">{{ formatDate(job.created_at) }}</span>
      </div>
      <PromptText class="job-prompt" :prompt="job.prompt" :assets="job.assets" />
      <div class="job-meta">
        <span>{{ job.seconds }} 秒</span>
        <span>{{ job.aspect_ratio }}</span>
        <span v-if="job.assets.some((asset) => asset.compressed)">参考图已压缩</span>
        <span v-if="job.assets.some((asset) => asset.original_duration_seconds !== null)">短音频已扩展</span>
        <span v-if="job.status === 'queued'">前方 {{ job.queue_ahead }} 个</span>
        <span v-else-if="job.elapsed_seconds !== null"><IconClock :size="15" />{{ formatDuration(job.elapsed_seconds) }}</span>
      </div>
    </div>
    <div class="job-assets">
      <AssetThumb v-for="asset in job.assets.slice(0, 4)" :key="asset.id" :asset="asset" compact />
      <span v-if="job.assets.length > 4" class="asset-overflow">+{{ job.assets.length - 4 }}</span>
    </div>
    <IconArrowRight class="row-arrow" :size="20" />
  </RouterLink>
</template>
