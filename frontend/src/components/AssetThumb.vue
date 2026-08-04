<script setup lang="ts">
import { IconFileMusic, IconMovie } from "@tabler/icons-vue"
import type { Asset } from "../api"
import ImagePreview from "./ImagePreview.vue"

withDefaults(defineProps<{ asset: Asset; compact?: boolean }>(), { compact: false })
</script>

<template>
  <div class="asset-thumb" :class="{ compact }">
    <ImagePreview v-if="asset.kind === 'image'" :src="asset.content_url" :thumbnail-src="asset.thumbnail_url" :alt="asset.original_name" />
    <img v-else-if="asset.thumbnail_url" :src="asset.thumbnail_url" :alt="asset.original_name" loading="lazy" decoding="async" fetchpriority="low" />
    <video v-else-if="asset.kind === 'video'" :src="asset.content_url" muted preload="metadata" />
    <IconMovie v-if="asset.kind === 'video'" class="asset-kind-icon" :size="compact ? 16 : 24" />
    <IconFileMusic v-if="asset.kind === 'audio'" :size="compact ? 20 : 30" />
  </div>
</template>
