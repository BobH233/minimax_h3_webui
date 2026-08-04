<script setup lang="ts">
import { nextTick, ref } from "vue"
import { IconX } from "@tabler/icons-vue"

const props = withDefaults(defineProps<{ src: string; thumbnailSrc?: string | null; alt: string; noDownload?: boolean }>(), { thumbnailSrc: "", noDownload: false })
const dialog = ref<HTMLDialogElement | null>(null)
const visible = ref(false)

async function open(event: Event): Promise<void> {
  event.preventDefault()
  event.stopPropagation()
  visible.value = true
  await nextTick()
  dialog.value?.showModal()
}

function close(): void {
  dialog.value?.close()
}

function closeBackdrop(event: MouseEvent): void {
  if (event.target === dialog.value) close()
}

function closed(): void {
  visible.value = false
}
</script>

<template>
  <img class="image-preview-trigger" :src="thumbnailSrc || src" :alt="alt" loading="lazy" decoding="async" fetchpriority="low" @click="open" @contextmenu="noDownload ? $event.preventDefault() : undefined" />
  <Teleport to="body">
    <dialog v-if="visible" ref="dialog" class="image-preview-dialog" :aria-label="alt" @click="closeBackdrop" @close="closed">
      <button class="image-preview-close" type="button" aria-label="关闭图片预览" @click="close"><IconX :size="22" /></button>
      <img class="image-preview-full" :src="src" :alt="alt" @contextmenu="noDownload ? $event.preventDefault() : undefined" />
    </dialog>
  </Teleport>
</template>
