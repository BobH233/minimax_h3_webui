<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue"
import { IconFileMusic, IconMovie } from "@tabler/icons-vue"
import type { Asset } from "../api"

const props = withDefaults(defineProps<{ modelValue: string; assets: Asset[]; disabled?: boolean }>(), { disabled: false })
const emit = defineEmits<{ "update:modelValue": [value: string] }>()
const composer = ref<HTMLElement | null>(null)
const textarea = ref<HTMLTextAreaElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const open = ref(false)
const active = ref(0)
const start = ref(0)
const replaceEnd = ref(0)
const replacing = ref(false)
const caret = ref(0)
const query = ref("")
const menuStyle = ref({ top: "0px", left: "8px" })

const mentionSet = computed(() => new Set(props.assets.map((asset) => asset.mention)))
const parts = computed(() => {
  const result: Array<{ text: string; kind: "mention" | "subject" | null; marker?: boolean }> = []
  const pattern = /@(图|视频|音频)\d+|<Subject\s+\d+>/giu
  const position = Math.min(caret.value, props.modelValue.length)
  let marked = false
  let cursor = 0

  function add(text: string, kind: "mention" | "subject" | null, offset: number): void {
    if (!marked && position >= offset && position <= offset + text.length) {
      const split = position - offset
      if (split) result.push({ text: text.slice(0, split), kind })
      result.push({ text: "", kind: null, marker: true })
      if (split < text.length) result.push({ text: text.slice(split), kind })
      marked = true
    } else if (text) result.push({ text, kind })
  }

  for (const match of props.modelValue.matchAll(pattern)) {
    const index = match.index || 0
    add(props.modelValue.slice(cursor, index), null, cursor)
    add(match[0], match[0].startsWith("<") ? "subject" : mentionSet.value.has(match[0]) ? "mention" : null, index)
    cursor = index + match[0].length
  }
  add(props.modelValue.slice(cursor), null, cursor)
  if (!marked) result.push({ text: "", kind: null, marker: true })
  if (!props.modelValue) result.push({ text: " ", kind: null })
  return result
})

const matches = computed(() => {
  const needle = query.value.toLocaleLowerCase()
  return props.assets.filter((asset) => {
    const kind = asset.kind === "image" ? "图片" : asset.kind === "video" ? "视频" : "音频"
    return `${asset.mention} ${asset.original_name} ${kind}`.toLocaleLowerCase().includes(needle)
  })
})

async function positionMenu(): Promise<void> {
  await nextTick()
  if (!open.value || !composer.value || !menu.value) return
  const caretMarker = composer.value.querySelector<HTMLElement>(".composer-caret-marker")
  if (!caretMarker) return
  const container = composer.value.getBoundingClientRect()
  const marker = caretMarker.getBoundingClientRect()
  const maxLeft = composer.value.clientWidth - menu.value.offsetWidth - 8
  menuStyle.value = {
    top: `${marker.bottom - container.top + 7}px`,
    left: `${Math.max(8, Math.min(marker.left - container.left, maxLeft))}px`,
  }
  menu.value.querySelector<HTMLElement>(".mention-option.active")?.scrollIntoView({ block: "nearest" })
}

function updateContext(): void {
  const input = textarea.value
  if (!input) return
  if (props.disabled) {
    open.value = false
    return
  }
  caret.value = input.selectionStart
  const existing = Array.from(props.modelValue.matchAll(/@(图|视频|音频)\d+/gu)).find((item) => {
    const index = item.index ?? 0
    return mentionSet.value.has(item[0]) && input.selectionStart >= index && input.selectionStart <= index + item[0].length
  })
  if (existing) {
    start.value = existing.index ?? 0
    replaceEnd.value = start.value + existing[0].length
    replacing.value = true
    query.value = ""
    active.value = Math.max(0, matches.value.findIndex((asset) => asset.mention === existing[0]))
    open.value = true
    void positionMenu()
    return
  }
  const before = props.modelValue.slice(0, input.selectionStart)
  const match = before.match(/@([^\s@<>]*)$/u)
  if (!match || !props.assets.length) {
    open.value = false
    replacing.value = false
    return
  }
  start.value = before.length - match[0].length
  replaceEnd.value = input.selectionStart
  replacing.value = false
  query.value = match[1]
  active.value = 0
  open.value = matches.value.length > 0
  if (open.value) void positionMenu()
}

function onInput(event: Event): void {
  emit("update:modelValue", (event.target as HTMLTextAreaElement).value)
  nextTick(updateContext)
}

async function resize(): Promise<void> {
  await nextTick()
  const input = textarea.value
  if (!input) return
  input.style.height = "auto"
  input.style.height = `${input.scrollHeight}px`
  input.scrollTop = 0
}

async function choose(asset: Asset): Promise<void> {
  const input = textarea.value
  if (!input || !asset.mention) return
  const separator = replacing.value ? "" : " "
  const value = `${props.modelValue.slice(0, start.value)}${asset.mention}${separator}${props.modelValue.slice(replaceEnd.value)}`
  emit("update:modelValue", value)
  open.value = false
  await nextTick()
  const caret = start.value + asset.mention.length + separator.length
  input.focus()
  input.setSelectionRange(caret, caret)
  replacing.value = false
}

function onKeydown(event: KeyboardEvent): void {
  if (!open.value) return
  if (event.key === "ArrowDown") {
    event.preventDefault()
    active.value = (active.value + 1) % matches.value.length
    void nextTick(() => menu.value?.querySelector<HTMLElement>(".mention-option.active")?.scrollIntoView({ block: "nearest" }))
  } else if (event.key === "ArrowUp") {
    event.preventDefault()
    active.value = (active.value - 1 + matches.value.length) % matches.value.length
    void nextTick(() => menu.value?.querySelector<HTMLElement>(".mention-option.active")?.scrollIntoView({ block: "nearest" }))
  } else if (event.key === "Enter" || event.key === "Tab") {
    event.preventDefault()
    void choose(matches.value[active.value])
  } else if (event.key === "Escape") {
    event.preventDefault()
    open.value = false
  }
}

function closeMenu(): void {
  window.setTimeout(() => { open.value = false }, 120)
}

watch(() => props.modelValue, () => void resize())
onMounted(() => void resize())
</script>

<template>
  <div ref="composer" class="mention-composer">
    <div class="composer-editor" :class="{ disabled }">
      <div class="composer-mirror" aria-hidden="true">
        <template v-for="(part, index) in parts" :key="index">
          <span v-if="part.marker" class="composer-caret-marker" />
          <span v-else :class="{ 'mention-tag': part.kind === 'mention', 'subject-tag': part.kind === 'subject' }">{{ part.text }}</span>
        </template>
      </div>
      <textarea
        ref="textarea"
        :value="modelValue"
        rows="1"
        maxlength="4000"
        :disabled="disabled"
        placeholder="描述视频内容，输入 @ 引用素材"
        @input="onInput"
        @click="updateContext"
        @select="updateContext"
        @keydown="onKeydown"
        @blur="closeMenu"
      />
    </div>
    <div v-if="open" ref="menu" class="mention-menu" role="listbox" :style="menuStyle">
      <button
        v-for="(asset, index) in matches"
        :key="asset.id"
        class="mention-option"
        :class="{ active: index === active }"
        type="button"
        @mousedown.prevent="choose(asset)"
      >
        <span class="mention-preview">
          <img v-if="asset.thumbnail_url" :src="asset.thumbnail_url" alt="" />
          <IconMovie v-else-if="asset.kind === 'video'" :size="20" />
          <IconFileMusic v-else :size="20" />
        </span>
        <span class="mention-token">{{ asset.mention }}</span>
        <span class="mention-name">{{ asset.original_name }}</span>
      </button>
    </div>
  </div>
</template>
