const BASE = '/api'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? res.statusText)
  }
  return res.json()
}

export interface Pattern {
  id: number
  name: string
  category: string
  language: string
  tags: string[]
  summary: string
  quality_signal?: string
  source_repo?: string
  source_file?: string
  line_start?: number
  line_end?: number
  updated_at: number
  user_notes?: string | null
  chunks?: { id: number; code_text: string; chunk_type: string }[]
}

export interface VaultStats {
  patterns: number
  chunks: number
  insights: number
  categories: string[]
  languages: string[]
}

export interface HealthStatus {
  status: string
  backend: string
  db_path: string
}

export interface ChatSession {
  id: number
  title: string | null
  source_repo?: string | null
  created_at: number
  updated_at: number
}

export interface ChatMessageRecord {
  id: number
  role: 'user' | 'assistant'
  content: string
  tool_calls: { name: string; input: Record<string, unknown>; result?: string }[]
  created_at: number
}

export interface Insight {
  id: number
  repo_path: string
  insight_text: string
  tags: string[]
  created_at: number
}

export interface ClonedRepo {
  id: number
  owner: string
  repo: string
  local_path: string
  source_url_base: string
  branch: string
  cloned_at: number
}

export const api = {
  health: () => request<HealthStatus>('/health'),
  stats: () => request<VaultStats>('/stats'),
  categories: () => request<string[]>('/categories'),
  tags: (category?: string) =>
    request<string[]>(category ? `/tags?category=${encodeURIComponent(category)}` : '/tags'),

  patterns: {
    list: (limit = 25) => request<Pattern[]>(`/patterns?limit=${limit}`),
    get: (id: number) => request<Pattern>(`/patterns/${id}`),
    search: (q: string, opts?: { category?: string; language?: string; limit?: number }) => {
      const params = new URLSearchParams({ q })
      if (opts?.category) params.set('category', opts.category)
      if (opts?.language) params.set('language', opts.language)
      if (opts?.limit) params.set('limit', String(opts.limit))
      return request<Pattern[]>(`/patterns/search?${params}`)
    },
    create: (data: Omit<Pattern, 'id' | 'updated_at' | 'chunks'> & { code_text: string }) =>
      request<{ id: number }>('/patterns', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<Pattern> & { code_text?: string }) =>
      request<{ status: string }>(`/patterns/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    delete: (id: number) =>
      request<{ status: string }>(`/patterns/${id}`, { method: 'DELETE' }),
  },

  history: {
    list: (limit = 50) => request<ChatSession[]>(`/history?limit=${limit}`),
    get: (id: number) => request<{ session_id: number; messages: ChatMessageRecord[] }>(`/history/${id}`),
    delete: (id: number) => request<{ status: string }>(`/history/${id}`, { method: 'DELETE' }),
    forRepo: (owner: string, repo: string): Promise<ChatSession | null> =>
      request<ChatSession>(`/history/repo/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`).catch(
        (e) => (e instanceof ApiError && e.status === 404 ? null : Promise.reject(e))
      ),
  },

  insights: {
    list: (limit = 50) => request<Insight[]>(`/insights?limit=${limit}`),
    get: (id: number) => request<Insight>(`/insights/${id}`),
    create: (data: { repo_path: string; insight_text: string; tags?: string[] }) =>
      request<{ id: number }>('/insights', { method: 'POST', body: JSON.stringify(data) }),
    delete: (id: number) => request<{ status: string }>(`/insights/${id}`, { method: 'DELETE' }),
  },

  workspace: {
    roots: () => request<{ path: string; name: string }[]>('/workspace/roots'),
    tree: (path: string) =>
      request<{ name: string; path: string; is_dir: boolean; size: number | null }[]>(
        `/workspace/tree?path=${encodeURIComponent(path)}`
      ),
    clone: (url: string) =>
      request<{ status: string; owner: string; repo: string; branch: string; local_path: string; source_url_base: string }>(
        '/workspace/clone',
        { method: 'POST', body: JSON.stringify({ url }) }
      ),
    cloned: () => request<ClonedRepo[]>('/workspace/cloned'),
  },
}
