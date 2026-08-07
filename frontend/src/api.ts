import { reactive } from "vue"

export type MediaKind = "image" | "video" | "audio"
export type JobStatus = "queued" | "submitting" | "generating" | "succeeded" | "failed" | "cancelled"

export interface User {
  id: string
  username: string
  weight: number
  is_admin: boolean
  is_active: boolean
  created_at: number
  job_count?: number
  asset_count?: number
}

export interface Asset {
  id: string
  kind: MediaKind
  original_name: string
  size_bytes: number
  compressed: boolean
  original_size_bytes: number | null
  duration_seconds: number | null
  original_duration_seconds: number | null
  created_at: number
  content_url: string
  thumbnail_url: string | null
  position?: number
  mention?: string
  canonical_label?: string
}

export interface Job {
  id: string
  prompt: string
  original_prompt: string | null
  status: JobStatus
  unread: boolean
  stage: string
  error: string | null
  progress: number
  progress_is_estimate: boolean
  seconds: number
  aspect_ratio: string
  seed: number
  num_inference_steps: number
  flow_shift: number
  audio_flow_shift: number
  created_at: number
  started_at: number | null
  completed_at: number | null
  generation_seconds: number | null
  elapsed_seconds: number | null
  queue_ahead: number
  assets: Asset[]
  download_url: string | null
  share_url?: string | null
  user?: Pick<User, "id" | "username" | "weight">
}

export interface PaginatedResponse<T> {
  items: T[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface AdminQueueResponse extends PaginatedResponse<Job> {
  status_counts: Record<string, number>
}

export interface PublicShare {
  id: string
  prompt: string
  seconds: number
  aspect_ratio: string
  seed: number
  num_inference_steps: number
  flow_shift: number
  audio_flow_shift: number
  created_at: number
  generation_seconds: number | null
  assets: Asset[]
  video_url: string
}

export interface GenerationConfig {
  sizes: Array<{ label: string; value: string }>
  limits: Record<string, number>
  defaults: {
    seconds: number
    aspect_ratio: string
    num_inference_steps: number
    flow_shift: number
    audio_flow_shift: number
  }
}

export interface GpuStatus {
  index: number
  name: string
  utilization: number
  memory_used_mb: number
  memory_total_mb: number
  power_w: number
  temperature_c: number
}

export interface BackendStatus {
  id: string
  name: string
  api_base: string
  gpu_ids: number[]
  online: boolean
  detail: string
  dispatch_enabled: boolean
  active_job: { id: string; status: JobStatus; stage: string } | null
}

export interface SystemStatus {
  sglang_online: boolean
  sglang_detail: string
  backends: BackendStatus[]
  gpus: GpuStatus[]
  job_counts: Record<string, number>
}

export interface LLMConfig {
  base_url: string
  model: string
  api_key_set: boolean
}

export type PromptStreamEvent =
  | { type: "start" }
  | { type: "delta"; text: string }
  | { type: "done"; text: string }
  | { type: "error"; detail: string }

export const auth = reactive<{
  initialized: boolean
  needsSetup: boolean
  user: User | null
  csrf: string
}>({ initialized: false, needsSetup: false, user: null, csrf: "" })

async function parseError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    if (typeof body.detail === "string") return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((item: { msg?: string }) => item.msg || "参数错误").join("\n")
  } catch {
    return `请求失败 (${response.status})`
  }
  return `请求失败 (${response.status})`
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || "GET").toUpperCase()
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData) && options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method) && auth.csrf) {
    headers.set("X-CSRF-Token", auth.csrf)
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" })
  if (response.status === 401) {
    auth.user = null
    auth.csrf = ""
  }
  if (!response.ok) throw new Error(await parseError(response))
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function streamApi<T>(path: string, options: RequestInit, onEvent: (event: T) => void): Promise<void> {
  const headers = new Headers(options.headers)
  if (!(options.body instanceof FormData) && options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  if (auth.csrf) headers.set("X-CSRF-Token", auth.csrf)
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" })
  if (!response.ok) throw new Error(await parseError(response))
  if (!response.body) throw new Error("浏览器不支持流式响应")

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let boundary = buffer.indexOf("\n\n")
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const data = block.split("\n").filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart()).join("\n")
        if (data) onEvent(JSON.parse(data) as T)
        boundary = buffer.indexOf("\n\n")
      }
      if (done) break
    }
  } finally {
    reader.releaseLock()
  }
}

export async function initializeAuth(): Promise<void> {
  const status = await api<{ needs_setup: boolean }>("/api/bootstrap/status")
  auth.needsSetup = status.needs_setup
  if (!status.needs_setup) {
    try {
      const result = await api<{ user: User; csrf_token: string }>("/api/auth/me")
      auth.user = result.user
      auth.csrf = result.csrf_token
    } catch {
      auth.user = null
    }
  }
  auth.initialized = true
}

export function applyAuth(result: { user: User; csrf_token: string }): void {
  auth.user = result.user
  auth.csrf = result.csrf_token
  auth.needsSetup = false
}

export function formatDate(timestamp: number | null): string {
  if (!timestamp) return "-"
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp * 1000))
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "-"
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes} 分 ${rest} 秒`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function formatAssetSize(asset: Asset): string {
  if (asset.compressed && asset.original_size_bytes !== null) {
    return `${formatBytes(asset.original_size_bytes)} → ${formatBytes(asset.size_bytes)} · 已压缩`
  }
  return formatBytes(asset.size_bytes)
}

export function formatAssetDuration(asset: Asset): string {
  if (asset.duration_seconds === null) return "-"
  const seconds = (value: number): string => `${Math.round(value * 10) / 10} 秒`
  if (
    asset.original_duration_seconds !== null
    && asset.original_duration_seconds + 0.01 < asset.duration_seconds
  ) {
    return `${seconds(asset.original_duration_seconds)} → ${seconds(asset.duration_seconds)} · 已扩展`
  }
  return seconds(asset.duration_seconds)
}
