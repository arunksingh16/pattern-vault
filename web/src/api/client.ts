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

export interface MCPStatus {
  running: boolean
  pid: number | null
  host: string
  port: number
  uptime_seconds: number | null
  command: string[]
}

export interface MCPToolInfo {
  name: string
  mode: 'read' | 'write'
  description: string
}

export interface WorkspaceIndexStats {
  files_discovered: number
  files_skipped: number
  files_scanned: number
  chunks_extracted: number
  patterns_found: number
  patterns_stored: number
  patterns_rejected: number
  current_stage: string
}

export type IndexingProfile = 'curated' | 'balanced' | 'comprehensive'

export interface WorkspaceIndexFilters {
  include_languages?: string[]
  include_paths?: string[]
  exclude_paths?: string[]
}

export interface WorkspaceIndexJob {
  job_id: string
  title: string
  source_kind: 'repo' | 'path'
  status: 'queued' | 'running' | 'completed' | 'completed_with_errors' | 'failed'
  path: string
  repo_name: string | null
  dry_run: boolean
  profile: IndexingProfile
  include_languages: string[]
  include_paths: string[]
  exclude_paths: string[]
  created_at: number
  started_at: number | null
  finished_at: number | null
  updated_at: number
  stats: WorkspaceIndexStats
  error: string | null
}

export interface WorkspaceIndexEvent {
  type: 'job_summary' | 'status' | 'log' | 'batch' | 'pattern_found' | 'done' | 'error'
  job?: WorkspaceIndexJob
  message?: string
  status?: WorkspaceIndexJob['status']
  recoverable?: boolean
  stage?: string
  range_start?: number
  range_end?: number
  category?: string
  name?: string
  stats: WorkspaceIndexStats
  errors?: string[]
}

export interface DailyTokenUsageRow {
  day: string
  provider: string
  requests: number
  input_tokens: number
  output_tokens: number
  total_tokens: number
  estimated_requests: number
}

export const api = {
  health: () => request<HealthStatus>('/health'),
  stats: () => request<VaultStats>('/stats'),
  usageDaily: (days = 14) => request<DailyTokenUsageRow[]>(`/usage/daily?days=${days}`),
  categories: () => request<string[]>('/categories'),
  tags: (category?: string) =>
    request<string[]>(category ? `/tags?category=${encodeURIComponent(category)}` : '/tags'),

  patterns: {
    list: (limit = 25, source_repo?: string) => {
      const params = new URLSearchParams({ limit: String(limit) })
      if (source_repo) params.set('source_repo', source_repo)
      return request<Pattern[]>(`/patterns?${params}`)
    },
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
    deleteRepo: (owner: string, repo: string) =>
      request<{ patterns_deleted: number; repo_deleted: boolean }>(
        `/workspace/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`,
        { method: 'DELETE' }
      ),
    startIndexForPath: (
      path: string,
      dryRun = false,
      profile: IndexingProfile = 'curated',
      filters: WorkspaceIndexFilters = {}
    ) =>
      request<WorkspaceIndexJob>('/workspace/index', {
        method: 'POST',
        body: JSON.stringify({ path, dry_run: dryRun, profile, ...filters }),
      }),
    startIndexForRepo: (
      owner: string,
      repo: string,
      dryRun = false,
      profile: IndexingProfile = 'curated',
      filters: WorkspaceIndexFilters = {}
    ) =>
      request<WorkspaceIndexJob>('/workspace/index', {
        method: 'POST',
        body: JSON.stringify({ repo: { owner, repo }, dry_run: dryRun, profile, ...filters }),
      }),
    indexStatus: (jobId: string) => request<WorkspaceIndexJob>(`/workspace/index/${encodeURIComponent(jobId)}`),
    indexJobs: (limit = 20) => request<WorkspaceIndexJob[]>(`/workspace/index-jobs?limit=${limit}`),
  },

  mcp: {
    status: () => request<MCPStatus>('/mcp/status'),
    start: () => request<MCPStatus>('/mcp/start', { method: 'POST' }),
    stop: () => request<MCPStatus>('/mcp/stop', { method: 'POST' }),
    tools: () => request<{ tools: MCPToolInfo[] }>('/mcp/tools'),
  },
}
