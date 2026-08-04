<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { IconUpload } from "@tabler/icons-vue"
import { api, formatBytes, formatDate, formatDuration, type Asset, type MediaKind } from "../api"
import AssetThumb from "../components/AssetThumb.vue"
import AudioPreview from "../components/AudioPreview.vue"

const assets = ref<Asset[]>([])
const filter = ref<"all" | MediaKind>("all")
const loading = ref(true)
const uploading = ref(false)
const error = ref("")
const input = ref<HTMLInputElement | null>(null)
const filters: Array<{ key: "all" | MediaKind; label: string }> = [
  { key: "all", label: "全部" },
  { key: "image", label: "图片" },
  { key: "video", label: "视频" },
  { key: "audio", label: "音频" },
]
const visible = computed(() => filter.value === "all" ? assets.value : assets.value.filter((asset) => asset.kind === filter.value))

async function upload(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement
  if (!target.files?.length) return
  uploading.value = true
  error.value = ""
  const body = new FormData()
  for (const file of target.files) body.append("files", file)
  try {
    const created = await api<Asset[]>("/api/assets", { method: "POST", body })
    assets.value = [...created, ...assets.value]
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "上传失败"
  } finally {
    uploading.value = false
    target.value = ""
  }
}

onMounted(async () => {
  try {
    assets.value = await api<Asset[]>("/api/assets")
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载失败"
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <header class="page-header">
      <div><h1>素材库</h1><p>上传的素材会永久保存在工作区。</p></div>
      <button class="primary-button" type="button" @click="input?.click()"><IconUpload :size="18" />{{ uploading ? "正在上传" : "上传素材" }}</button>
      <input ref="input" class="visually-hidden" type="file" multiple accept="image/*,video/*,audio/*" @change="upload" />
    </header>
    <div class="toolbar">
      <div class="filter-tabs">
        <button v-for="item in filters" :key="item.key" type="button" :class="{ active: filter === item.key }" @click="filter = item.key">{{ item.label }}</button>
      </div>
      <span>{{ visible.length }} 个素材</span>
    </div>
    <p v-if="error" class="form-error page-error">{{ error }}</p>
    <div v-if="loading" class="asset-grid"><div v-for="item in 8" :key="item" class="asset-skeleton" /></div>
    <div v-else-if="visible.length" class="asset-grid">
      <article v-for="asset in visible" :key="asset.id" class="asset-card">
        <AssetThumb :asset="asset" />
        <AudioPreview v-if="asset.kind === 'audio'" :src="asset.content_url" />
        <div class="asset-card-copy"><strong>{{ asset.original_name }}</strong><span>{{ formatBytes(asset.size_bytes) }}<template v-if="asset.duration_seconds"> / {{ formatDuration(asset.duration_seconds) }}</template></span><time>{{ formatDate(asset.created_at) }}</time></div>
      </article>
    </div>
    <div v-else class="empty-state"><IconUpload :size="34" :stroke-width="1.5" /><h2>素材库为空</h2><button type="button" @click="input?.click()">上传素材</button></div>
  </div>
</template>
