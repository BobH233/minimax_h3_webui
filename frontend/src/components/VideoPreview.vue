<script setup lang="ts">
import { nextTick, ref } from "vue"
import { IconX } from "@tabler/icons-vue"

const props = withDefaults(defineProps<{ src: string; thumbnailSrc?: string | null; alt: string }>(), { thumbnailSrc: "" })
const dialog = ref<HTMLDialogElement | null>(null)
const player = ref<HTMLVideoElement | null>(null)
const visible = ref(false)

async function open(event: Event): Promise<void> {
  event.preventDefault()
  event.stopPropagation()
  visible.value = true
  await nextTick()
  dialog.value?.showModal()
  void player.value?.play()
}

function close(): void {
  player.value?.pause()
  dialog.value?.close()
}

function closeBackdrop(event: MouseEvent): void {
  if (event.target === dialog.value) close()
}

function closed(): void {
  player.value?.pause()
  visible.value = false
}
</script>

<template>
  <img v-if="thumbnailSrc" class="video-preview-trigger" :src="thumbnailSrc" :alt="alt" loading="lazy" decoding="async" fetchpriority="low" @click="open" />
  <video v-else class="video-preview-trigger" :src="src" muted preload="metadata" @click="open" />
  <Teleport to="body">
    <dialog v-if="visible" ref="dialog" class="image-preview-dialog" :aria-label="alt" @click="closeBackdrop" @close="closed">
      <button class="image-preview-close" type="button" aria-label="关闭视频预览" @click="close"><IconX :size="22" /></button>
      <video ref="player" class="video-preview-full" :src="src" controls autoplay preload="metadata" @click.stop />
    </dialog>
  </Teleport>
</template>
