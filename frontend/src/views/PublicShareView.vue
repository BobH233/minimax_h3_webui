<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import { IconFileMusic, IconMovie } from "@tabler/icons-vue"
import { api, formatAssetDuration, formatAssetSize, formatDate, formatDuration, type PublicShare } from "../api"
import ImagePreview from "../components/ImagePreview.vue"
import PromptText from "../components/PromptText.vue"

const route = useRoute()
const share = ref<PublicShare | null>(null)
const error = ref("")

onMounted(async () => {
  try {
    share.value = await api<PublicShare>(`/api/public/shares/${route.params.token}`)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "分享加载失败"
  }
})
</script>

<template>
  <main class="public-share-page">
    <header class="public-share-header">
      <div class="auth-brand"><span class="brand-mark">H3</span><span>MiniMax Workspace</span></div>
      <span v-if="share">{{ formatDate(share.created_at) }}</span>
    </header>

    <section v-if="error" class="public-share-error">
      <IconMovie :size="34" :stroke-width="1.5" />
      <h1>{{ error }}</h1>
    </section>

    <template v-else-if="share">
      <video class="public-result-video" :src="share.video_url" controls controlslist="nodownload noremoteplayback" disablepictureinpicture preload="metadata" @contextmenu.prevent />

      <div class="public-share-grid">
        <section class="detail-block prompt-block">
          <h2>提示词</h2>
          <PromptText :prompt="share.prompt" :assets="share.assets" />
        </section>
        <section class="detail-block metrics-block">
          <h2>生成信息</h2>
          <dl>
            <div><dt>时长</dt><dd>{{ share.seconds }} 秒</dd></div>
            <div><dt>比例</dt><dd>{{ share.aspect_ratio }}</dd></div>
            <div><dt>Seed</dt><dd>{{ share.seed }}</dd></div>
            <div><dt>推理步数</dt><dd>{{ share.num_inference_steps }}</dd></div>
            <div><dt>生成耗时</dt><dd>{{ formatDuration(share.generation_seconds) }}</dd></div>
          </dl>
        </section>
      </div>

      <section class="detail-block">
        <h2>参考素材</h2>
        <div class="public-assets">
          <article v-for="asset in share.assets" :key="asset.id" class="public-asset-card">
            <ImagePreview v-if="asset.kind === 'image'" :src="asset.content_url" :thumbnail-src="asset.thumbnail_url" :alt="asset.original_name" no-download />
            <video v-else-if="asset.kind === 'video'" :src="asset.content_url" controls controlslist="nodownload noremoteplayback" disablepictureinpicture preload="metadata" @contextmenu.prevent />
            <div v-else class="public-audio">
              <IconFileMusic :size="28" />
              <audio :src="asset.content_url" controls controlslist="nodownload noremoteplayback" preload="metadata" @contextmenu.prevent />
            </div>
            <div class="public-asset-copy"><strong>{{ asset.mention }}</strong><span>{{ asset.original_name }}</span><span>{{ formatAssetSize(asset) }}<template v-if="asset.duration_seconds"> / {{ formatAssetDuration(asset) }}</template></span></div>
          </article>
        </div>
      </section>
    </template>

    <div v-else class="skeleton-detail"><div /><div /><div /></div>
  </main>
</template>
