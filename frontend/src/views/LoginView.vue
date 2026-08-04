<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import { IconArrowRight } from "@tabler/icons-vue"
import { api, applyAuth, type User } from "../api"

const router = useRouter()
const username = ref("")
const password = ref("")
const error = ref("")
const loading = ref(false)

async function submit(): Promise<void> {
  error.value = ""
  loading.value = true
  try {
    const result = await api<{ user: User; csrf_token: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    applyAuth(result)
    await router.push("/create")
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "登录失败"
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <section class="auth-panel">
      <div class="auth-brand"><span class="brand-mark">H3</span><span>MiniMax Workspace</span></div>
      <div class="auth-copy">
        <h1>登录工作区</h1>
        <p>继续创建和管理视频任务。</p>
      </div>
      <form class="auth-form" @submit.prevent="submit">
        <label>
          <span>用户名</span>
          <input v-model="username" autocomplete="username" required autofocus />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <button class="primary-button wide-button" type="submit" :disabled="loading">
          {{ loading ? "正在登录" : "登录" }}
          <IconArrowRight :size="18" />
        </button>
      </form>
    </section>
  </main>
</template>
