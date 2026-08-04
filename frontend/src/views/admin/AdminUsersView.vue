<script setup lang="ts">
import { onMounted, ref } from "vue"
import { IconKey, IconPlus, IconTrash, IconUserCheck, IconUserOff } from "@tabler/icons-vue"
import { api, auth, formatDate, type User } from "../../api"

const users = ref<User[]>([])
const username = ref("")
const password = ref("")
const weight = ref(0)
const error = ref("")
const creating = ref(false)
const passwordFor = ref<string | null>(null)
const newPassword = ref("")

async function load(): Promise<void> {
  users.value = await api<User[]>("/api/admin/users")
}

async function createUser(): Promise<void> {
  creating.value = true
  error.value = ""
  try {
    await api<User>("/api/admin/users", { method: "POST", body: JSON.stringify({ username: username.value, password: password.value, weight: weight.value }) })
    username.value = ""
    password.value = ""
    weight.value = 0
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "创建失败"
  } finally {
    creating.value = false
  }
}

async function update(user: User, changes: Record<string, unknown>): Promise<void> {
  error.value = ""
  try {
    await api<User>(`/api/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify(changes) })
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "更新失败"
  }
}

async function savePassword(user: User): Promise<void> {
  await update(user, { password: newPassword.value })
  passwordFor.value = null
  newPassword.value = ""
}

async function remove(user: User): Promise<void> {
  if (!window.confirm(`停用并删除用户 ${user.username}？`)) return
  try {
    await api(`/api/admin/users/${user.id}`, { method: "DELETE" })
    await load()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "删除失败"
  }
}

onMounted(() => load().catch((caught: unknown) => { error.value = caught instanceof Error ? caught.message : "加载失败" }))
</script>

<template>
  <div class="page">
    <header class="page-header"><div><h1>用户</h1><p>管理账号和队列优先级。</p></div></header>
    <form class="inline-create" @submit.prevent="createUser">
      <label><span>用户名</span><input v-model="username" minlength="2" maxlength="32" required /></label>
      <label><span>初始密码</span><input v-model="password" type="password" minlength="8" required /></label>
      <label class="weight-field"><span>权重</span><input v-model.number="weight" type="number" min="0" max="100" required /></label>
      <button class="primary-button" type="submit" :disabled="creating"><IconPlus :size="18" />{{ creating ? "创建中" : "添加用户" }}</button>
    </form>
    <p v-if="error" class="form-error page-error">{{ error }}</p>

    <div class="user-list">
      <article v-for="user in users" :key="user.id" class="user-row" :class="{ inactive: !user.is_active }">
        <span class="account-avatar large-avatar">{{ user.username.slice(0, 1).toUpperCase() }}</span>
        <div class="user-identity"><strong>{{ user.username }}</strong><span>{{ user.is_admin ? "管理员" : user.is_active ? "已启用" : "已停用" }} / {{ formatDate(user.created_at) }}</span></div>
        <div class="user-count"><strong>{{ user.job_count || 0 }}</strong><span>任务</span></div>
        <div class="user-count"><strong>{{ user.asset_count || 0 }}</strong><span>素材</span></div>
        <label class="inline-weight"><span>权重</span><input :value="user.weight" type="number" min="0" max="100" :disabled="user.is_admin" @change="update(user, { weight: Number(($event.target as HTMLInputElement).value) })" /></label>
        <div class="row-actions user-actions">
          <button v-if="!user.is_admin" class="icon-button" type="button" :aria-label="user.is_active ? '停用' : '启用'" @click="update(user, { is_active: !user.is_active })"><IconUserOff v-if="user.is_active" :size="18" /><IconUserCheck v-else :size="18" /></button>
          <button class="icon-button" type="button" aria-label="修改密码" @click="passwordFor = passwordFor === user.id ? null : user.id"><IconKey :size="18" /></button>
          <button v-if="!user.is_admin && user.id !== auth.user?.id" class="icon-button danger-icon" type="button" aria-label="删除用户" @click="remove(user)"><IconTrash :size="18" /></button>
        </div>
        <form v-if="passwordFor === user.id" class="password-row" @submit.prevent="savePassword(user)"><input v-model="newPassword" type="password" minlength="8" placeholder="输入新密码" required /><button class="secondary-button" type="submit">保存密码</button></form>
      </article>
    </div>
  </div>
</template>
