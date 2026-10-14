/**
 * API 统一响应类型（与后端 ApiResponse Schema 对齐）
 */
export interface ApiResp<T = unknown> {
  ok: boolean
  message: string
  data: T
}

/**
 * API 请求封装 — 自动加超时 + JSON Content-Type
 */
export async function api<T = unknown>(
  url: string,
  options: RequestInit = {},
): Promise<ApiResp<T>> {
  // 未指定 signal 时加 2 分钟超时
  if (!options.signal) {
    try {
      options.signal = AbortSignal.timeout(120000)
    } catch {
      /* 兼容旧浏览器 */
    }
  }
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const body = (await resp.json()) as ApiResp<T>
  if (!body.ok) {
    const msg = body.message || (body as unknown as Record<string, unknown>).detail || JSON.stringify(body)
    throw new Error(String(msg))
  }
  return body
}
