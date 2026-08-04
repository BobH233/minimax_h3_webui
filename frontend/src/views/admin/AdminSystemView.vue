<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { IconBolt, IconCpu, IconDeviceFloppy, IconRefresh } from "@tabler/icons-vue"
import { api, type LLMConfig, type SystemStatus } from "../../api"

const status = ref<SystemStatus | null>(null)
const error = ref("")
const refreshing = ref(false)
const baseUrl = ref("")
const model = ref("")
const apiKey = ref("")
const apiKeySet = ref(false)
const llmBusy = ref(false)
const llmMessage = ref("")
const llmFailed = ref(false)
let timer = 0
const queued = computed(() => status.value?.job_counts.queued || 0)
const active = computed(() => (status.value?.job_counts.generating || 0) + (status.value?.job_counts.submitting || 0))

async function load(): Promise<void> {
  refreshing.value = true
  try {
    status.value = await api<SystemStatus>("/api/admin/system")
    error.value = ""
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载失败"
  } finally {
    refreshing.value = false
  }
}

async function loadLlmConfig(): Promise<void> {
  try {
    const config = await api<LLMConfig>("/api/admin/llm-config")
    baseUrl.value = config.base_url
    model.value = config.model
    apiKeySet.value = config.api_key_set
  } catch (caught) {
    llmFailed.value = true
    llmMessage.value = caught instanceof Error ? caught.message : "配置加载失败"
  }
}

function llmBody(): Record<string, string> {
  const body: Record<string, string> = { base_url: baseUrl.value, model: model.value }
  if (apiKey.value) body.api_key = apiKey.value
  return body
}

async function saveLlmConfig(): Promise<void> {
  llmBusy.value = true
  llmMessage.value = ""
  try {
    const config = await api<LLMConfig>("/api/admin/llm-config", { method: "PUT", body: JSON.stringify(llmBody()) })
    baseUrl.value = config.base_url
    model.value = config.model
    apiKeySet.value = config.api_key_set
    apiKey.value = ""
    llmFailed.value = false
    llmMessage.value = "配置已保存"
  } catch (caught) {
    llmFailed.value = true
    llmMessage.value = caught instanceof Error ? caught.message : "保存失败"
  } finally {
    llmBusy.value = false
  }
}

async function testLlmConfig(): Promise<void> {
  llmBusy.value = true
  llmMessage.value = ""
  try {
    const result = await api<{ latency_ms: number; reply: string }>("/api/admin/llm-config/test", { method: "POST", body: JSON.stringify(llmBody()) })
    llmFailed.value = false
    llmMessage.value = `连接成功 · ${result.latency_ms} ms · ${result.reply}`
  } catch (caught) {
    llmFailed.value = true
    llmMessage.value = caught instanceof Error ? caught.message : "连接失败"
  } finally {
    llmBusy.value = false
  }
}

onMounted(() => {
  void load()
  void loadLlmConfig()
  timer = window.setInterval(() => void load(), 5000)
})
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="page">
    <header class="page-header"><div><h1>系统</h1><p>SGLang 服务和 8 卡运行状态。</p></div><button class="secondary-button" type="button" :disabled="refreshing" @click="load"><IconRefresh :size="18" />刷新</button></header>
    <p v-if="error" class="form-error page-error">{{ error }}</p>
    <div v-if="status" class="system-overview">
      <section class="service-status" :class="{ online: status.sglang_online }"><span>SGLang</span><strong>{{ status.sglang_online ? "在线" : "离线" }}</strong><p>{{ status.sglang_detail }}</p></section>
      <section class="system-number"><span>等待任务</span><strong>{{ queued }}</strong></section>
      <section class="system-number"><span>执行中</span><strong>{{ active }}</strong></section>
      <section class="system-number"><span>GPU</span><strong>{{ status.gpus.length }}</strong></section>
    </div>
    <section class="llm-settings">
      <div class="section-heading"><h2>提示词优化模型</h2><span>{{ apiKeySet ? "API Key 已保存" : "未设置 API Key" }}</span></div>
      <form class="llm-settings-form" @submit.prevent="saveLlmConfig">
        <label><span>Base URL</span><input v-model="baseUrl" type="url" placeholder="https://api.openai.com/v1" required /></label>
        <label><span>模型</span><input v-model="model" type="text" placeholder="gpt-5-mini" required /></label>
        <label><span>API Key</span><input v-model="apiKey" type="password" :placeholder="apiKeySet ? '已保存' : 'API Key'" autocomplete="off" /></label>
        <div class="llm-settings-actions">
          <button class="secondary-button" type="button" :disabled="llmBusy || !baseUrl || !model" @click="testLlmConfig"><IconBolt :size="18" />测试连接</button>
          <button class="primary-button" type="submit" :disabled="llmBusy || !baseUrl || !model"><IconDeviceFloppy :size="18" />保存</button>
        </div>
      </form>
      <p v-if="llmMessage" class="llm-message" :class="{ failed: llmFailed }">{{ llmMessage }}</p>
    </section>
    <section class="gpu-section">
      <div class="section-heading"><h2>GPU</h2><span>{{ status?.gpus.length || 0 }} 张</span></div>
      <div v-if="status?.gpus.length" class="gpu-grid">
        <article v-for="gpu in status.gpus" :key="gpu.index" class="gpu-card">
          <header><span class="gpu-index">GPU {{ gpu.index }}</span><strong>{{ Math.round(gpu.utilization) }}%</strong></header>
          <div class="gpu-util"><span :style="{ width: `${gpu.utilization}%` }" /></div>
          <p>{{ gpu.name }}</p>
          <dl>
            <div><dt>显存</dt><dd>{{ (gpu.memory_used_mb / 1024).toFixed(1) }} / {{ (gpu.memory_total_mb / 1024).toFixed(1) }} GB</dd></div>
            <div><dt>温度</dt><dd>{{ gpu.temperature_c }}°C</dd></div>
            <div><dt>功耗</dt><dd>{{ Math.round(gpu.power_w) }} W</dd></div>
          </dl>
          <div class="memory-bar"><span :style="{ width: `${gpu.memory_used_mb / gpu.memory_total_mb * 100}%` }" /></div>
        </article>
      </div>
      <div v-else class="empty-state compact-empty"><IconCpu :size="34" :stroke-width="1.5" /><h2>未读取到 GPU</h2></div>
    </section>
  </div>
</template>
