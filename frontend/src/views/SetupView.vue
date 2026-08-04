<script setup lang="ts">
import { ref } from "vue"
import { useRouter } from "vue-router"
import { IconArrowRight, IconLock } from "@tabler/icons-vue"
import { api, applyAuth, type User } from "../api"

const router = useRouter()
const username = ref("")
const password = ref("")
const confirmPassword = ref("")
const error = ref("")
const loading = ref(false)

async function submit(): Promise<void> {
  error.value = ""
  if (password.value !== confirmPassword.value) {
    error.value = "两次输入的密码不一致"
    return
  }
  loading.value = true
  try {
    const result = await api<{ user: User; csrf_token: string }>("/api/bootstrap", {
      method: "POST",
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    applyAuth(result)
    await router.push("/create")
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "创建失败"
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
        <IconLock :size="26" :stroke-width="1.7" />
        <h1>创建管理员</h1>
        <p>设置工作区的第一个账号。</p>
      </div>
      <form class="auth-form" @submit.prevent="submit">
        <label>
          <span>用户名</span>
          <input v-model="username" autocomplete="username" minlength="2" maxlength="32" required autofocus />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="new-password" minlength="8" required />
        </label>
        <label>
          <span>确认密码</span>
          <input v-model="confirmPassword" type="password" autocomplete="new-password" minlength="8" required />
        </label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <button class="primary-button wide-button" type="submit" :disabled="loading">
          {{ loading ? "正在创建" : "创建并进入" }}
          <IconArrowRight :size="18" />
        </button>
      </form>
    </section>
  </main>
</template>
