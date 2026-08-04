<script setup lang="ts">
import { computed } from "vue"
import type { Asset } from "../api"

const props = defineProps<{ prompt: string; assets: Asset[] }>()

const parts = computed(() => {
  const mentions = new Set(props.assets.map((asset) => asset.mention).filter(Boolean))
  const result: Array<{ text: string; kind: "mention" | "subject" | null }> = []
  const pattern = /@(图|视频|音频)\d+|<Subject\s+\d+>/giu
  let cursor = 0
  for (const match of props.prompt.matchAll(pattern)) {
    const index = match.index ?? 0
    if (index > cursor) result.push({ text: props.prompt.slice(cursor, index), kind: null })
    result.push({
      text: match[0],
      kind: match[0].startsWith("<") ? "subject" : mentions.has(match[0]) ? "mention" : null,
    })
    cursor = index + match[0].length
  }
  if (cursor < props.prompt.length) result.push({ text: props.prompt.slice(cursor), kind: null })
  return result
})
</script>

<template>
  <span class="prompt-rich-text"><span v-for="(part, index) in parts" :key="index" :class="{ 'mention-tag': part.kind === 'mention', 'subject-tag': part.kind === 'subject' }">{{ part.text }}</span></span>
</template>
