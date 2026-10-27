/**
 * 轻量 GET 缓存：内存 + 请求去重 + 可选 sessionStorage
 *
 * 目的：看板/统计这类重接口在切页面、组件重新挂载、重复点击时不再重复请求。
 * - cachedApi(url, { ttl, force })：命中缓存直接返回；同 URL 并发只发一次请求
 * - peekCached(url, ttl)：同步读取，用于“有缓存就先渲染，不显示 loading”
 * - invalidateCache(prefix)：数据变更后主动失效（如生成报告后）
 */
import { api } from './utils';

type Entry = { ts: number; data: any };

const memory = new Map<string, Entry>();
const inflight = new Map<string, Promise<any>>();
const SESSION_PREFIX = 'apicache:';

export function peekCached<T = any>(url: string, ttl = 0, useSession = false): T | null {
  const now = Date.now();
  const mem = memory.get(url);
  if (mem && (ttl <= 0 || now - mem.ts < ttl)) return mem.data as T;
  if (useSession) {
    try {
      const raw = sessionStorage.getItem(SESSION_PREFIX + url);
      if (raw) {
        const entry = JSON.parse(raw) as Entry;
        if (ttl <= 0 || now - entry.ts < ttl) {
          memory.set(url, entry);
          return entry.data as T;
        }
      }
    } catch { /* sessionStorage 不可用则忽略 */ }
  }
  return null;
}

export function invalidateCache(prefix = ''): void {
  for (const key of Array.from(memory.keys())) {
    if (!prefix || key.startsWith(prefix)) memory.delete(key);
  }
  try {
    const keys: string[] = [];
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const k = sessionStorage.key(i) || '';
      if (k.startsWith(SESSION_PREFIX)) keys.push(k);
    }
    for (const k of keys) {
      const url = k.slice(SESSION_PREFIX.length);
      if (!prefix || url.startsWith(prefix)) sessionStorage.removeItem(k);
    }
  } catch { /* ignore */ }
}

export async function cachedApi<T = any>(
  url: string,
  opts: { ttl?: number; force?: boolean; useSession?: boolean } = {},
): Promise<{ ok: boolean; message: string; data: T; [k: string]: unknown }> {
  const { ttl = 60000, force = false, useSession = false } = opts;
  if (!force) {
    const hit = peekCached<any>(url, ttl, useSession);
    if (hit) return hit;
    const running = inflight.get(url);
    if (running) return running;
  }
  const task = api<any>(url)
    .then((res) => {
      const entry: Entry = { ts: Date.now(), data: res };
      memory.set(url, entry);
      if (useSession) {
        try { sessionStorage.setItem(SESSION_PREFIX + url, JSON.stringify(entry)); } catch { /* ignore */ }
      }
      return res;
    })
    .finally(() => { inflight.delete(url); });
  inflight.set(url, task);
  return task as Promise<{ ok: boolean; message: string; data: T; [k: string]: unknown }>;
}
