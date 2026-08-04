<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import {
  IconArrowDown,
  IconArrowUp,
  IconCheck,
  IconDice,
  IconPlus,
  IconSparkles,
  IconTrash,
  IconUpload,
} from "@tabler/icons-vue"
import { api, formatBytes, streamApi, type Asset, type GenerationConfig, type Job, type MediaKind, type PromptStreamEvent } from "../api"
import AssetThumb from "../components/AssetThumb.vue"
import AudioPreview from "../components/AudioPreview.vue"
import MentionComposer from "../components/MentionComposer.vue"

const router = useRouter()
const assets = ref<Asset[]>([])
const selected = ref<Asset[]>([])
const config = ref<GenerationConfig | null>(null)
const prompt = ref("")
const seconds = ref(5)
const aspectRatio = ref("16:9")
const seed = ref(0)
const steps = ref(50)
const flowShift = ref(12)
const audioFlowShift = ref(3)
const uploading = ref(false)
const submitting = ref(false)
const optimizing = ref(false)
const error = ref("")
const optimizeError = ref("")
const fileInput = ref<HTMLInputElement | null>(null)
const filter = ref<"all" | MediaKind>("all")
const assetFilters: Array<{ key: "all" | MediaKind; name: string }> = [
  { key: "all", name: "全部" },
  { key: "image", name: "图片" },
  { key: "video", name: "视频" },
  { key: "audio", name: "音频" },
]

const kindNames: Record<MediaKind, string> = { image: "图", video: "视频", audio: "音频" }
const counts = computed(() => selected.value.reduce<Record<MediaKind, number>>(
  (total, asset) => ({ ...total, [asset.kind]: total[asset.kind] + 1 }),
  { image: 0, video: 0, audio: 0 },
))
const selectedWithMentions = computed(() => withMentions(selected.value))
const visibleAssets = computed(() => filter.value === "all" ? assets.value : assets.value.filter((asset) => asset.kind === filter.value))
const selectedIds = computed(() => new Set(selected.value.map((asset) => asset.id)))

function withMentions(items: Asset[]): Asset[] {
  const counter: Record<MediaKind, number> = { image: 0, video: 0, audio: 0 }
  return items.map((asset) => ({ ...asset, mention: `@${kindNames[asset.kind]}${++counter[asset.kind]}` }))
}

function rewriteReferences(before: Asset[], after: Asset[]): void {
  const oldByMention = new Map(withMentions(before).map((asset) => [asset.mention as string, asset.id]))
  const newById = new Map(withMentions(after).map((asset) => [asset.id, asset.mention as string]))
  prompt.value = prompt.value.replace(/@(图|视频|音频)\d+/gu, (mention) => {
    const id = oldByMention.get(mention)
    return id ? newById.get(id) || "@已删除" : mention
  })
}

function toggleAsset(asset: Asset): void {
  if (optimizing.value) return
  const before = [...selected.value]
  const index = selected.value.findIndex((item) => item.id === asset.id)
  if (index >= 0) selected.value.splice(index, 1)
  else selected.value.push(asset)
  rewriteReferences(before, selected.value)
}

function moveAsset(index: number, direction: -1 | 1): void {
  if (optimizing.value) return
  const target = index + direction
  if (target < 0 || target >= selected.value.length) return
  const before = [...selected.value]
  const next = [...selected.value]
  ;[next[index], next[target]] = [next[target], next[index]]
  selected.value = next
  rewriteReferences(before, next)
}

function mediaFiles(files: FileList | File[]): File[] {
  return Array.from(files).filter((file) => /^(image|video|audio)\//u.test(file.type) || /\.(jpe?g|png|webp|mp4|mov|webm|mp3|wav|m4a|flac|ogg)$/iu.test(file.name))
}

async function uploadFiles(files: File[]): Promise<void> {
  if (!files.length || optimizing.value || uploading.value) return
  error.value = ""
  uploading.value = true
  const body = new FormData()
  for (const file of files) body.append("files", file)
  try {
    const created = await api<Asset[]>("/api/assets", { method: "POST", body })
    assets.value = [...created, ...assets.value]
    const before = [...selected.value]
    selected.value.push(...created)
    rewriteReferences(before, selected.value)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "上传失败"
  } finally {
    uploading.value = false
  }
}

function upload(event: Event): void {
  const input = event.target as HTMLInputElement
  if (input.files) void uploadFiles(mediaFiles(input.files))
  input.value = ""
}

function pasteFiles(event: ClipboardEvent): void {
  if (!event.clipboardData) return
  const files = mediaFiles(event.clipboardData.files)
  if (!files.length) return
  event.preventDefault()
  void uploadFiles(files)
}

function dropFiles(event: DragEvent): void {
  if (!event.dataTransfer) return
  void uploadFiles(mediaFiles(event.dataTransfer.files))
}

function randomSeed(): void {
  seed.value = Math.floor(Math.random() * 4294967296)
}

async function optimizePrompt(): Promise<void> {
  const original = prompt.value
  if (!original.trim()) {
    optimizeError.value = "请先输入提示词"
    return
  }
  optimizing.value = true
  optimizeError.value = ""
  let receiving = false
  let completed = false
  try {
    await streamApi<PromptStreamEvent>(
      "/api/prompt/optimize",
      { method: "POST", body: JSON.stringify({ prompt: original }) },
      (event) => {
        if (event.type === "delta") {
          if (!receiving) prompt.value = ""
          receiving = true
          prompt.value += event.text
        } else if (event.type === "done") {
          prompt.value = event.text
          completed = true
        } else if (event.type === "error") {
          throw new Error(event.detail)
        }
      },
    )
    if (!completed) throw new Error("提示词优化响应未完成")
  } catch (caught) {
    prompt.value = original
    optimizeError.value = caught instanceof Error ? caught.message : "提示词优化失败"
  } finally {
    optimizing.value = false
  }
}

async function submit(): Promise<void> {
  error.value = ""
  submitting.value = true
  try {
    const job = await api<Job>("/api/jobs", {
      method: "POST",
      body: JSON.stringify({
        prompt: prompt.value,
        asset_ids: selected.value.map((asset) => asset.id),
        seconds: seconds.value,
        aspect_ratio: aspectRatio.value,
        seed: seed.value,
        num_inference_steps: steps.value,
        flow_shift: flowShift.value,
        audio_flow_shift: audioFlowShift.value,
      }),
    })
    await router.push(`/jobs/${job.id}`)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "任务提交失败"
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  try {
    ;[assets.value, config.value] = await Promise.all([
      api<Asset[]>("/api/assets"),
      api<GenerationConfig>("/api/config"),
    ])
    seconds.value = config.value.defaults.seconds
    aspectRatio.value = config.value.defaults.aspect_ratio
    steps.value = config.value.defaults.num_inference_steps
    flowShift.value = config.value.defaults.flow_shift
    audioFlowShift.value = config.value.defaults.audio_flow_shift
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载失败"
  }
})
</script>

<template>
  <div class="page create-page" @paste="pasteFiles" @dragover.prevent @drop.prevent="dropFiles">
    <header class="page-header">
      <div><h1>新建视频</h1><p>组合参考素材并提交到生成队列。</p></div>
      <button class="secondary-button" type="button" :disabled="optimizing || uploading" @click="fileInput?.click()">
        <IconUpload :size="18" />{{ uploading ? "正在上传" : "上传素材" }}
      </button>
      <input ref="fileInput" class="visually-hidden" type="file" multiple accept="image/*,video/*,audio/*" :disabled="optimizing || uploading" @change="upload" />
    </header>

    <form class="create-layout" @submit.prevent="submit">
      <section class="composer-column">
        <div class="section-heading"><h2>提示词</h2><span>{{ prompt.length }} / {{ config?.limits.prompt_max_chars || 8000 }}</span></div>
        <MentionComposer v-model="prompt" :assets="selectedWithMentions" :disabled="optimizing" :max-length="config?.limits.prompt_max_chars || 8000" />
        <div class="prompt-actions">
          <p v-if="optimizeError" class="form-error">{{ optimizeError }}</p>
          <button class="secondary-button optimize-prompt-button" type="button" :disabled="optimizing || submitting || !prompt.trim()" @click="optimizePrompt">
            <IconSparkles :size="18" />{{ optimizing ? "正在优化提示词" : "智能优化提示词" }}
          </button>
        </div>

        <div class="section-heading selected-heading">
          <h2>参考素材</h2>
          <span>{{ selected.length }} / 12</span>
        </div>
        <div v-if="selectedWithMentions.length" class="selected-list">
          <div v-for="(asset, index) in selectedWithMentions" :key="asset.id" class="selected-row">
            <AssetThumb :asset="asset" compact />
            <div class="selected-copy"><strong>{{ asset.mention }}</strong><span>{{ asset.original_name }}</span></div>
            <div class="row-actions">
              <AudioPreview v-if="asset.kind === 'audio'" :src="asset.content_url" compact />
              <button class="icon-button" type="button" aria-label="上移" :disabled="optimizing || index === 0" @click="moveAsset(index, -1)"><IconArrowUp :size="17" /></button>
              <button class="icon-button" type="button" aria-label="下移" :disabled="optimizing || index === selected.length - 1" @click="moveAsset(index, 1)"><IconArrowDown :size="17" /></button>
              <button class="icon-button danger-icon" type="button" aria-label="移除" :disabled="optimizing" @click="toggleAsset(asset)"><IconTrash :size="17" /></button>
            </div>
          </div>
        </div>
        <button v-else class="empty-drop" type="button" :disabled="optimizing" @click="fileInput?.click()"><IconPlus :size="22" />添加图片、视频或音频</button>

        <div class="library-head">
          <div class="filter-tabs">
            <button v-for="item in assetFilters" :key="item.key" type="button" :class="{ active: filter === item.key }" @click="filter = item.key">{{ item.name }}</button>
          </div>
          <span>{{ assets.length }} 个素材</span>
        </div>
        <div v-if="visibleAssets.length" class="asset-picker">
          <div v-for="asset in visibleAssets" :key="asset.id" class="asset-choice" :class="{ selected: selectedIds.has(asset.id) }">
            <button class="asset-choice-select" type="button" :disabled="optimizing" @click="toggleAsset(asset)">
              <AssetThumb :asset="asset" />
              <span class="asset-choice-name">{{ asset.original_name }}</span>
              <span class="asset-choice-size">{{ formatBytes(asset.size_bytes) }}</span>
              <span v-if="selectedIds.has(asset.id)" class="selected-check"><IconCheck :size="15" /></span>
            </button>
            <AudioPreview v-if="asset.kind === 'audio'" :src="asset.content_url" />
          </div>
        </div>
        <div v-else class="empty-state compact-empty">素材库为空</div>
      </section>

      <aside class="settings-column">
        <div class="settings-panel">
          <h2>生成参数</h2>
          <label><span>时长</span><select v-model.number="seconds"><option v-for="value in 12" :key="value" :value="value + 3">{{ value + 3 }} 秒</option></select></label>
          <label><span>画面比例</span><select v-model="aspectRatio"><option v-for="size in config?.sizes || []" :key="size.value" :value="size.value">{{ size.label }}</option></select></label>
          <label><span>Seed</span><div class="input-action"><input v-model.number="seed" type="number" min="0" max="4294967295" /><button type="button" aria-label="随机 Seed" @click="randomSeed"><IconDice :size="18" /></button></div></label>
          <label><span>推理步数</span><input v-model.number="steps" type="number" min="1" max="100" /></label>
          <details>
            <summary>高级参数</summary>
            <div class="advanced-fields">
              <label><span>Video flow shift</span><input v-model.number="flowShift" type="number" min="0" max="30" step="0.1" /></label>
              <label><span>Audio flow shift</span><input v-model.number="audioFlowShift" type="number" min="0" max="30" step="0.1" /></label>
            </div>
          </details>
          <div class="selection-summary"><span>已选 {{ selected.length }} 个</span><span>图片 {{ counts.image }} / 视频 {{ counts.video }} / 音频 {{ counts.audio }}</span></div>
          <p v-if="error" class="form-error">{{ error }}</p>
          <button class="primary-button wide-button" type="submit" :disabled="submitting || uploading || optimizing">
            {{ submitting ? "正在提交" : "加入生成队列" }}
          </button>
        </div>
      </aside>
    </form>
  </div>
</template>
