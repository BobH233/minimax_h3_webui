<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { IconArrowLeft, IconCopy, IconDownload, IconLinkOff, IconPlayerStop, IconRefresh, IconShare3 } from "@tabler/icons-vue"
import { api, auth, formatAssetDuration, formatAssetSize, formatDate, formatDuration, type Job } from "../api"
import AssetThumb from "../components/AssetThumb.vue"
import PromptText from "../components/PromptText.vue"
import StatusBadge from "../components/StatusBadge.vue"
import VideoPreview from "../components/VideoPreview.vue"

const route = useRoute()
const router = useRouter()
const job = ref<Job | null>(null)
const error = ref("")
const cancelling = ref(false)
const sharing = ref(false)
const copied = ref(false)
let timer = 0
let mounted = false
let markingViewed = false

const active = computed(() => job.value && ["queued", "submitting", "generating"].includes(job.value.status))
const canReuse = computed(() => Boolean(
  job.value?.original_prompt && (!job.value.user || job.value.user.id === auth.user?.id),
))

function goBack(): void {
  const previous = window.history.state?.back
  const path = typeof previous === "string" ? previous.split(/[?#]/u)[0] : ""
  if (path === "/jobs" || path === "/admin/queue") router.back()
  else void router.push(job.value?.user ? "/admin/queue" : "/jobs")
}

function reuse(): void {
  if (job.value) void router.push({ path: "/create", query: { from_job: job.value.id } })
}

async function load(): Promise<void> {
  try {
    const loaded = await api<Job>(`/api/jobs/${route.params.id}`)
    if (!mounted) return
    job.value = loaded
    error.value = ""
    if (loaded.status === "succeeded" && loaded.unread && !document.hidden && !markingViewed) {
      markingViewed = true
      try {
        await api(`/api/jobs/${loaded.id}/viewed`, { method: "POST" })
        if (mounted && job.value?.id === loaded.id) job.value.unread = false
      } finally {
        markingViewed = false
      }
    }
    if (!active.value) window.clearInterval(timer)
  } catch (caught) {
    if (!mounted) return
    error.value = caught instanceof Error ? caught.message : "加载失败"
  }
}

async function cancel(): Promise<void> {
  if (!job.value || !window.confirm("取消这个排队任务？")) return
  cancelling.value = true
  try {
    job.value = await api<Job>(`/api/jobs/${job.value.id}/cancel`, { method: "POST" })
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "取消失败"
  } finally {
    cancelling.value = false
  }
}

async function copyShare(): Promise<void> {
  if (!job.value?.share_url) return
  const url = new URL(job.value.share_url, window.location.origin).toString()
  if (navigator.clipboard) await navigator.clipboard.writeText(url)
  else window.prompt("复制分享链接", url)
  copied.value = true
  window.setTimeout(() => { copied.value = false }, 1600)
}

async function share(): Promise<void> {
  if (!job.value) return
  sharing.value = true
  try {
    const result = await api<{ share_url: string }>(`/api/jobs/${job.value.id}/share`, { method: "POST" })
    job.value.share_url = result.share_url
    await copyShare()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "分享失败"
  } finally {
    sharing.value = false
  }
}

async function unshare(): Promise<void> {
  if (!job.value || !window.confirm("取消公开分享？原链接将立即失效。")) return
  sharing.value = true
  try {
    await api(`/api/jobs/${job.value.id}/share`, { method: "DELETE" })
    job.value.share_url = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "取消分享失败"
  } finally {
    sharing.value = false
  }
}

onMounted(() => {
  mounted = true
  void load()
  timer = window.setInterval(() => void load(), 2500)
})
onBeforeUnmount(() => {
  mounted = false
  window.clearInterval(timer)
})
</script>

<template>
  <div class="page detail-page">
    <button class="back-link" type="button" @click="goBack"><IconArrowLeft :size="18" />返回任务</button>
    <p v-if="error" class="form-error page-error">{{ error }}</p>
    <div v-if="!job" class="skeleton-detail"><div /><div /><div /></div>
    <template v-else>
      <header class="detail-header">
        <div class="detail-title"><StatusBadge :status="job.status" /><h1>{{ job.stage }}</h1><p v-if="job.user">{{ job.user.username }}，权重 {{ job.user.weight }}</p></div>
        <div class="header-actions">
          <button v-if="canReuse" class="secondary-button" type="button" @click="reuse"><IconRefresh :size="18" />一键重新生成</button>
          <button v-if="job.status === 'queued'" class="secondary-button danger-button" type="button" :disabled="cancelling" @click="cancel"><IconPlayerStop :size="18" />取消排队</button>
          <button v-if="job.status === 'succeeded' && !job.share_url" class="secondary-button" type="button" :disabled="sharing" @click="share"><IconShare3 :size="18" />公开分享</button>
          <button v-if="job.share_url" class="secondary-button" type="button" :disabled="sharing" @click="copyShare"><IconCopy :size="18" />{{ copied ? "已复制" : "复制分享链接" }}</button>
          <button v-if="job.share_url" class="secondary-button share-revoke-button" type="button" aria-label="取消分享" :disabled="sharing" @click="unshare"><IconLinkOff :size="18" /></button>
          <a v-if="job.download_url" class="primary-button" :href="job.download_url"><IconDownload :size="18" />下载视频</a>
        </div>
      </header>

      <section v-if="job.status === 'queued'" class="queue-position"><strong>{{ job.queue_ahead }}</strong><span>个任务在前方</span></section>
      <section v-else-if="['submitting', 'generating'].includes(job.status)" class="progress-section">
        <div class="progress-copy"><span>{{ job.stage }}</span><strong>{{ Math.round(job.progress) }}%</strong></div>
        <div class="progress-track"><span :style="{ width: `${job.progress}%` }" /></div>
        <span v-if="job.progress_is_estimate" class="muted-text">进度为预计值</span>
      </section>

      <VideoPreview v-if="job.status === 'succeeded' && job.download_url" :src="job.download_url" alt="生成视频" trigger-class="result-video" inline-controls />
      <p v-if="job.error" class="error-panel">{{ job.error }}</p>

      <div class="detail-grid">
        <section class="detail-block prompt-block">
          <h2>提示词</h2>
          <PromptText :prompt="job.prompt" :assets="job.assets" />
          <div v-if="job.original_prompt" class="original-prompt">
            <h2>优化前提示词</h2>
            <PromptText :prompt="job.original_prompt" :assets="job.assets" />
          </div>
        </section>
        <section class="detail-block metrics-block">
          <h2>任务信息</h2>
          <dl>
            <div><dt>时长</dt><dd>{{ job.seconds }} 秒</dd></div>
            <div><dt>比例</dt><dd>{{ job.aspect_ratio }}</dd></div>
            <div><dt>Seed</dt><dd>{{ job.seed }}</dd></div>
            <div><dt>推理步数</dt><dd>{{ job.num_inference_steps }}</dd></div>
            <div><dt>提交时间</dt><dd>{{ formatDate(job.created_at) }}</dd></div>
            <div><dt>生成耗时</dt><dd>{{ formatDuration(job.generation_seconds ?? job.elapsed_seconds) }}</dd></div>
          </dl>
        </section>
      </div>

      <section class="detail-block"><h2>参考素材</h2><div class="detail-assets"><div v-for="asset in job.assets" :key="asset.id" class="detail-asset"><AssetThumb :asset="asset" video-preview /><strong>{{ asset.mention }}</strong><span>{{ asset.original_name }}</span><small>{{ formatAssetSize(asset) }}<template v-if="asset.duration_seconds"> / {{ formatAssetDuration(asset) }}</template></small></div></div></section>
    </template>
  </div>
</template>
