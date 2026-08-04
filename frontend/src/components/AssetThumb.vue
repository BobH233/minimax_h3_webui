<script setup lang="ts">
import { IconFileMusic, IconMovie } from "@tabler/icons-vue"
import type { Asset } from "../api"

withDefaults(defineProps<{ asset: Asset; compact?: boolean }>(), { compact: false })
</script>

<template>
  <div class="asset-thumb" :class="{ compact }">
    <img v-if="asset.kind === 'image' || asset.thumbnail_url" :src="asset.thumbnail_url || asset.content_url" :alt="asset.original_name" loading="lazy" decoding="async" fetchpriority="low" />
    <video v-else-if="asset.kind === 'video'" :src="asset.content_url" muted preload="metadata" />
    <IconMovie v-if="asset.kind === 'video'" class="asset-kind-icon" :size="compact ? 16 : 24" />
    <IconFileMusic v-if="asset.kind === 'audio'" :size="compact ? 20 : 30" />
  </div>
</template>
