import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type ClonedRepo, type ChatSession, type WorkspaceIndexJob } from '@/api/client'
import { useUIStore } from '@/stores/uiStore'
import { useChatStore } from '@/stores/chatStore'

interface TreeEntry {
  name: string
  path: string
  is_dir: boolean
  size: number | null
}

function FileTreeNode({ entry }: { entry: TreeEntry }) {
  const [expanded, setExpanded] = useState(false)
  const { data: children } = useQuery({
    queryKey: ['workspace-tree', entry.path],
    queryFn: () => api.workspace.tree(entry.path),
    enabled: entry.is_dir && expanded,
  })

  if (!entry.is_dir) {
    return (
      <div className="flex items-center gap-2 py-1 px-2 text-sm text-on-surface-variant hover:bg-surface-bright/30 rounded cursor-default">
        <span className="material-symbols-outlined text-[16px] text-outline">description</span>
        <span className="truncate">{entry.name}</span>
        {entry.size !== null && (
          <span className="ml-auto text-[10px] text-outline">{formatSize(entry.size)}</span>
        )}
      </div>
    )
  }

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 py-1 px-2 text-sm text-on-surface hover:bg-surface-bright/30 rounded w-full text-left"
      >
        <span className="material-symbols-outlined text-[16px] text-primary">
          {expanded ? 'folder_open' : 'folder'}
        </span>
        <span className="truncate font-medium">{entry.name}</span>
        <span className="material-symbols-outlined text-[12px] text-outline ml-auto">
          {expanded ? 'expand_more' : 'chevron_right'}
        </span>
      </button>
      {expanded && children && (
        <div className="ml-4 border-l border-outline-variant/20 pl-1">
          {children.map((child) => (
            <FileTreeNode key={child.path} entry={child} />
          ))}
          {children.length === 0 && (
            <span className="text-[11px] text-outline px-2 py-1 block">Empty</span>
          )}
        </div>
      )}
    </div>
  )
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}K`
  return `${(bytes / 1048576).toFixed(1)}M`
}

export function ExplorerPanel() {
  const qc = useQueryClient()
  const setActiveView = useUIStore((s) => s.setActiveView)
  const setPendingAnalyse = useUIStore((s) => s.setPendingAnalyse)
  const setActiveIndexJob = useUIStore((s) => s.setActiveIndexJob)
  const loadSession = useChatStore((s) => s.loadSession)
  const setRepoContext = useChatStore((s) => s.setRepoContext)
  const clearChat = useChatStore((s) => s.clearChat)

  // Per-repo state: spinner and continue/fresh prompt
  const [analysingRepoId, setAnalysingRepoId] = useState<number | null>(null)
  const [indexingRepoId, setIndexingRepoId] = useState<number | null>(null)
  const [promptState, setPromptState] = useState<{ repo: ClonedRepo; session: ChatSession } | null>(null)
  const [dryRunIndexing, setDryRunIndexing] = useState(false)
  const [indexError, setIndexError] = useState<string | null>(null)

  // Local workspace tree state
  const { data: roots, isLoading } = useQuery({
    queryKey: ['workspace-roots'],
    queryFn: api.workspace.roots,
  })
  const [selectedRoot, setSelectedRoot] = useState<string | null>(null)
  useEffect(() => {
    if (roots && roots.length > 0 && !selectedRoot) {
      setSelectedRoot(roots[0].path)
    }
  }, [roots, selectedRoot])
  const [localIndexPath, setLocalIndexPath] = useState('')
  useEffect(() => {
    if (selectedRoot) {
      setLocalIndexPath(selectedRoot)
    }
  }, [selectedRoot])
  const { data: tree } = useQuery({
    queryKey: ['workspace-tree', selectedRoot],
    queryFn: () => api.workspace.tree(selectedRoot!),
    enabled: !!selectedRoot,
  })

  // Cloned repos registry
  const { data: clonedRepos } = useQuery({
    queryKey: ['cloned-repos'],
    queryFn: api.workspace.cloned,
  })
  const { data: recentIndexJobs } = useQuery({
    queryKey: ['index-jobs'],
    queryFn: () => api.workspace.indexJobs(8),
    refetchInterval: 5000,
  })

  // Clone form state
  const [cloneUrl, setCloneUrl] = useState('')
  const cloneMutation = useMutation({
    mutationFn: (url: string) => api.workspace.clone(url),
    onSuccess: () => {
      setCloneUrl('')
      qc.invalidateQueries({ queryKey: ['cloned-repos'] })
    },
  })

  function handleClone(e: React.FormEvent) {
    e.preventDefault()
    if (!cloneUrl.trim() || cloneMutation.isPending) return
    cloneMutation.mutate(cloneUrl.trim())
  }

  function buildAnalyseMsg(repo: ClonedRepo): string {
    return `Please analyse this GitHub repository and find reusable patterns:\n\n**${repo.owner}/${repo.repo}** (${repo.branch})\nLocal path: \`${repo.local_path}\`\n\nStart by scanning the directory structure, then explore interesting files.`
  }

  async function handleAnalyse(repo: ClonedRepo) {
    setAnalysingRepoId(repo.id)
    setPromptState(null)
    try {
      const existingSession = await api.history.forRepo(repo.owner, repo.repo)
      if (existingSession) {
        setPromptState({ repo, session: existingSession })
      } else {
        setPendingAnalyse({ message: buildAnalyseMsg(repo), repoOwner: repo.owner, repoName: repo.repo })
        setActiveView('copilot')
      }
    } finally {
      setAnalysingRepoId(null)
    }
  }

  async function handleContinue(repo: ClonedRepo, session: ChatSession) {
    setPromptState(null)
    const result = await api.history.get(session.id)
    const messages = result.messages.map((m) => ({
      id: `hist-${m.id}`,
      role: m.role,
      content: m.content,
      toolCalls: m.tool_calls,
    }))
    loadSession(messages, session.id)
    setRepoContext({ owner: repo.owner, repo: repo.repo })
    setActiveView('copilot')
  }

  function handleStartFresh(repo: ClonedRepo) {
    setPromptState(null)
    clearChat()
    setPendingAnalyse({ message: buildAnalyseMsg(repo), repoOwner: repo.owner, repoName: repo.repo })
    setActiveView('copilot')
  }

  async function handleRepoIndex(repo: ClonedRepo) {
    if (indexingRepoId !== null) return
    setIndexingRepoId(repo.id)
    setIndexError(null)
    try {
      const job = await api.workspace.startIndexForRepo(repo.owner, repo.repo, dryRunIndexing)
      setActiveIndexJob({
        jobId: job.job_id,
        title: job.title,
        path: job.path,
        repoName: job.repo_name,
        sourceKind: job.source_kind,
        dryRun: job.dry_run,
      })
      void qc.invalidateQueries({ queryKey: ['index-jobs'] })
      setActiveView('ingestion')
    } catch (error) {
      setIndexError(formatIndexError(error))
    } finally {
      setIndexingRepoId(null)
    }
  }

  async function handleLocalIndex() {
    if (!localIndexPath.trim()) return
    setIndexError(null)
    try {
      const job = await api.workspace.startIndexForPath(localIndexPath.trim(), dryRunIndexing)
      setActiveIndexJob({
        jobId: job.job_id,
        title: job.title,
        path: job.path,
        repoName: job.repo_name,
        sourceKind: job.source_kind,
        dryRun: job.dry_run,
      })
      void qc.invalidateQueries({ queryKey: ['index-jobs'] })
      setActiveView('ingestion')
    } catch (error) {
      setIndexError(formatIndexError(error))
    }
  }

  function handleOpenJob(job: WorkspaceIndexJob) {
    setActiveIndexJob({
      jobId: job.job_id,
      title: job.title,
      path: job.path,
      repoName: job.repo_name,
      sourceKind: job.source_kind,
      dryRun: job.dry_run,
    })
    setActiveView('ingestion')
  }

  return (
    <div className="flex-1 glass-panel p-6 flex flex-col gap-6 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="material-symbols-outlined text-primary text-[28px]">folder_open</span>
        <h2 className="font-sans text-headline-md font-semibold text-on-surface">Explorer</h2>
      </div>

      {/* GitHub clone section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-label-caps text-outline uppercase">Clone GitHub Repo</span>
          <label className="flex items-center gap-2 text-[11px] font-mono text-on-surface-variant uppercase">
            <input
              type="checkbox"
              checked={dryRunIndexing}
              onChange={(e) => setDryRunIndexing(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-outline-variant/30 bg-surface-container-lowest"
            />
            Dry run index only
          </label>
        </div>
        <form onSubmit={handleClone} className="flex gap-2">
          <input
            type="text"
            value={cloneUrl}
            onChange={(e) => setCloneUrl(e.target.value)}
            placeholder="https://github.com/owner/repo"
            className="flex-1 bg-surface-container-lowest border border-outline-variant/30 rounded-lg px-3 py-2 text-sm font-mono text-on-surface placeholder:text-outline/50 focus:outline-none focus:border-primary/50"
          />
          <button
            type="submit"
            disabled={!cloneUrl.trim() || cloneMutation.isPending}
            className="px-4 py-2 bg-primary/10 hover:bg-primary/20 text-primary rounded-lg font-mono text-[11px] uppercase transition-colors disabled:opacity-40 flex items-center gap-1.5"
          >
            {cloneMutation.isPending ? (
              <span className="material-symbols-outlined text-[14px] animate-spin">progress_activity</span>
            ) : (
              <span className="material-symbols-outlined text-[14px]">download</span>
            )}
            {cloneMutation.isPending ? 'Cloning…' : 'Clone'}
          </button>
        </form>
        {cloneMutation.isError && (
          <p className="text-error text-[11px] font-mono">
            {(cloneMutation.error as Error)?.message ?? 'Clone failed'}
          </p>
        )}
        {cloneMutation.isSuccess && (
          <p className="text-tertiary text-[11px] font-mono">Cloned successfully!</p>
        )}
        {indexError && (
          <p className="text-error text-[11px] font-mono">{indexError}</p>
        )}
      </div>

      {/* Previously cloned repos */}
      {clonedRepos && clonedRepos.length > 0 && (
        <div className="space-y-2">
          <span className="font-mono text-label-caps text-outline uppercase">Cloned Repos</span>
          <div className="space-y-1.5">
            {clonedRepos.map((repo) => (
              <div key={repo.id} className="space-y-0">
                <div
                  className="flex items-center gap-3 px-3 py-2 bg-surface-container-lowest/50 border border-outline-variant/20 rounded-lg"
                >
                  <span className="material-symbols-outlined text-[16px] text-primary">code</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-mono text-on-surface truncate">{repo.owner}/{repo.repo}</p>
                    <p className="text-[10px] text-outline truncate">{repo.branch} · {new Date(repo.cloned_at * 1000).toLocaleDateString()}</p>
                  </div>
                  <button
                    onClick={() => handleAnalyse(repo)}
                    disabled={analysingRepoId === repo.id}
                    className="flex items-center gap-1 px-2 py-1 text-primary hover:bg-primary/10 rounded text-[10px] font-mono uppercase transition-colors shrink-0 disabled:opacity-50"
                  >
                    {analysingRepoId === repo.id ? (
                      <span className="material-symbols-outlined text-[13px] animate-spin">progress_activity</span>
                    ) : (
                      <span className="material-symbols-outlined text-[13px]">psychology</span>
                    )}
                    Copilot
                  </button>
                  <button
                    onClick={() => handleRepoIndex(repo)}
                    disabled={indexingRepoId === repo.id}
                    className="flex items-center gap-1 px-2 py-1 text-secondary hover:bg-secondary/10 rounded text-[10px] font-mono uppercase transition-colors shrink-0 disabled:opacity-50"
                  >
                    {indexingRepoId === repo.id ? (
                      <span className="material-symbols-outlined text-[13px] animate-spin">progress_activity</span>
                    ) : (
                      <span className="material-symbols-outlined text-[13px]">deployed_code</span>
                    )}
                    Index
                  </button>
                </div>

                {/* Continue / Start Fresh inline prompt */}
                {promptState?.repo.id === repo.id && (
                  <div className="mx-1 px-3 py-2.5 bg-primary/5 border border-primary/20 rounded-b-lg space-y-2">
                    <p className="text-[11px] text-on-surface-variant font-mono">
                      Last analysed{' '}
                      <span className="text-on-surface">
                        {new Date(promptState.session.updated_at * 1000).toLocaleDateString()}
                      </span>
                      . Continue that session or start fresh?
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleContinue(repo, promptState.session)}
                        className="flex-1 px-3 py-1.5 bg-primary/10 hover:bg-primary/20 text-primary rounded text-[10px] font-mono uppercase transition-colors"
                      >
                        Continue
                      </button>
                      <button
                        onClick={() => handleStartFresh(repo)}
                        className="flex-1 px-3 py-1.5 bg-surface-container-highest/50 hover:bg-surface-container-highest text-on-surface-variant rounded text-[10px] font-mono uppercase transition-colors"
                      >
                        Start Fresh
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {recentIndexJobs && recentIndexJobs.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <span className="font-mono text-label-caps text-outline uppercase">Recent Index Jobs</span>
            <span className="font-mono text-[10px] text-outline uppercase">Reconnect after refresh</span>
          </div>
          <div className="space-y-1.5">
            {recentIndexJobs.map((job) => (
              <button
                key={job.job_id}
                onClick={() => handleOpenJob(job)}
                className="w-full rounded-lg border border-outline-variant/20 bg-surface-container-lowest/40 px-3 py-2 text-left hover:border-primary/30 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className={`material-symbols-outlined text-[16px] ${job.status === 'running' ? 'text-tertiary' : job.status === 'failed' ? 'text-secondary' : 'text-primary'}`}>
                    {job.source_kind === 'repo' ? 'deployed_code' : 'folder_open'}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-on-surface">{job.title}</p>
                      <span className="rounded bg-surface-container-high px-2 py-0.5 text-[10px] uppercase text-on-surface-variant">
                        {job.source_kind}
                      </span>
                      {job.dry_run && (
                        <span className="rounded bg-secondary/15 px-2 py-0.5 text-[10px] uppercase text-secondary">dry run</span>
                      )}
                    </div>
                    <p className="mt-1 truncate text-[11px] text-outline">{job.path}</p>
                  </div>
                  <div className="text-right">
                    <p className={`text-[10px] font-mono uppercase ${job.status === 'running' ? 'text-tertiary' : job.status === 'failed' ? 'text-secondary' : 'text-primary'}`}>{job.status}</p>
                    <p className="mt-1 text-[10px] text-outline">{new Date(job.updated_at * 1000).toLocaleString()}</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Local workspace tree */}
      <div className="flex-1 flex flex-col gap-2 min-h-0">
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-label-caps text-outline uppercase">Workspace</span>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={localIndexPath}
              onChange={(e) => setLocalIndexPath(e.target.value)}
              placeholder="/path/to/project"
              className="w-72 max-w-full bg-surface-container-lowest border border-outline-variant/30 rounded-lg px-3 py-2 text-xs font-mono text-on-surface placeholder:text-outline/50 focus:outline-none focus:border-primary/50"
            />
            <button
              type="button"
              onClick={handleLocalIndex}
              disabled={!localIndexPath.trim()}
              className="px-3 py-2 bg-secondary/10 hover:bg-secondary/20 text-secondary rounded-lg font-mono text-[11px] uppercase transition-colors disabled:opacity-40"
            >
              Index Path
            </button>
          </div>
        </div>

        {roots && roots.length > 1 && (
          <div className="flex gap-2">
            {roots.map((root) => (
              <button
                key={root.path}
                onClick={() => setSelectedRoot(root.path)}
                className={`px-3 py-1 text-xs rounded border transition-colors ${
                  selectedRoot === root.path
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : 'border-outline-variant/30 text-on-surface-variant hover:border-primary/30'
                }`}
              >
                {root.name}
              </button>
            ))}
          </div>
        )}

        {selectedRoot && (
          <div className="font-mono text-[11px] text-outline px-2 py-1 bg-surface-container-lowest rounded truncate">
            {selectedRoot}
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {isLoading && (
            <div className="space-y-2">
              {[...Array(8)].map((_, i) => (
                <div key={i} className="h-6 rounded bg-surface-container-high/50 animate-pulse" />
              ))}
            </div>
          )}
          {tree?.map((entry) => (
            <FileTreeNode key={entry.path} entry={entry} />
          ))}
        </div>
      </div>
    </div>
  )
}

function formatIndexError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Index job failed to start.'
}
