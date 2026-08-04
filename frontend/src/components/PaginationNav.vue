<script setup lang="ts">
import { IconChevronLeft, IconChevronRight } from "@tabler/icons-vue"

defineProps<{ page: number; totalPages: number }>()
const emit = defineEmits<{ change: [page: number] }>()
</script>

<template>
  <nav v-if="totalPages > 1" class="pagination" aria-label="分页">
    <button class="secondary-button" type="button" :disabled="page <= 1" @click="emit('change', page - 1)">
      <IconChevronLeft :size="17" />上一页
    </button>
    <span>第 {{ page }} / {{ totalPages }} 页</span>
    <button class="secondary-button" type="button" :disabled="page >= totalPages" @click="emit('change', page + 1)">
      下一页<IconChevronRight :size="17" />
    </button>
  </nav>
</template>
