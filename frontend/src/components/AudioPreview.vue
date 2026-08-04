<script lang="ts">
let activeAudio: HTMLAudioElement | null = null
</script>

<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue"
import { IconPlayerPause, IconPlayerPlay } from "@tabler/icons-vue"

withDefaults(defineProps<{ src: string; compact?: boolean }>(), { compact: false })

const audio = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
const loading = ref(false)

async function toggle(): Promise<void> {
  const current = audio.value
  if (!current) return
  if (!current.paused) {
    current.pause()
    return
  }
  loading.value = true
  const previous = activeAudio
  activeAudio = current
  if (previous && previous !== current) previous.pause()
  try {
    await current.play()
  } catch {
    onPause()
  } finally {
    loading.value = false
  }
}

function onPlay(): void {
  playing.value = true
  activeAudio = audio.value
}

function onPause(): void {
  playing.value = false
  if (activeAudio === audio.value) activeAudio = null
}

onBeforeUnmount(() => audio.value?.pause())
</script>

<template>
  <div class="audio-preview">
    <button class="audio-preview-button" :class="{ compact, playing }" type="button" :aria-label="playing ? '暂停试听' : '试听音频'" :disabled="loading" @click.stop="toggle">
      <IconPlayerPause v-if="playing" :size="16" />
      <IconPlayerPlay v-else :size="16" />
      <span v-if="!compact">{{ loading ? "加载中" : playing ? "暂停" : "试听" }}</span>
    </button>
    <audio ref="audio" :src="src" preload="none" @play="onPlay" @pause="onPause" @ended="onPause" />
  </div>
</template>
