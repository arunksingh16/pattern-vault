import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type WorkspaceIndexJob, type Pattern } from '@/api/client'
import { GlassPanel } from '@/components/GlassPanel'
import { useUIStore } from '@/stores/uiStore'
import { useIngestion } from '@/api/hooks/useIngestion'

const STAGES = [
  { id: 'scan', label: 'Scan Workspace', icon: 'folder_search' },
  { id: 'extract', label: 'Extract Candidates', icon: 'schema' },
  { id: 'store', label: 'Store Patterns', icon: 'database' },
  { id: 'complete', label: 'Complete', icon: 'task_alt' },
] as const

export function IngestionPanel() {
  const activeIndexJob = useUIStore((s) => s.activeIndexJob)
  const setActiveView = useUIStore((s) => s.setActiveView)
  const openIndexJob = useUIStore((s) => s.openIndexJob)
  const clearActiveIndexJob = useUIStore((s) => s.clearActiveIndexJob)
  const logViewportRef = useRef<HTMLDivElement | null>(null)
  const { job, logs, discoveries, error } = useIngestion(activeIndexJob?.jobId ?? null)
  const { data: recentJobs } = useQuery({
    queryKey: ['index-jobs'],
    queryFn: () => api.workspace.indexJobs(10),
    refetchInterval: 5000,
  })

  useEffect(() => {
    const viewport = logViewportRef.current
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight
    }
  }, [logs])

  const stats = job?.stats ?? {
    files_discovered: 0,
    files_skipped: 0,
    files_scanned: 0,
    chunks_extracted: 0,
    patterns_found: 0,
    patterns_stored: 0,
    patterns_rejected: 0,
    current_stage: 'queued',
  }

  const statusLabel = useMemo(() => {
    if (!job) return 'Preparing'
    if (job.status === 'completed') return job.dry_run ? 'Dry Run Complete' : 'Index Complete'
    if (job.status === 'completed_with_errors') return 'Complete With Warnings'
    if (job.status === 'failed') return 'Index Failed'
    if (job.status === 'running') return 'Scanning Live'
    return 'Queued'
  }, [job])

  if (!activeIndexJob) {
    return (
      <div className="flex-1 min-h-0 grid gap-6 xl:grid-cols-[0.8fr_1.2fr]">
        <GlassPanel className="p-8 flex flex-col items-center justify-center gap-4">
          <span className="material-symbols-outlined text-[40px] text-outline">deployed_code</span>
          <div className="text-center space-y-2">
            <h2 className="font-sans text-headline-md font-semibold text-on-surface">No Active Ingestion Job</h2>
            <p className="text-sm text-on-surface-variant">Start an index from Explorer or reopen a recent job below.</p>
          </div>
          <button
            type="button"
            onClick={() => setActiveView('explorer')}
            className="px-4 py-2 rounded bg-primary text-on-primary font-mono text-[11px] uppercase"
          >
            Open Explorer
          </button>
        </GlassPanel>
        <GlassPanel className="p-6 min-h-0 flex flex-col gap-4 overflow-hidden">
          <div className="flex items-center justify-between gap-4">
            <h3 className="font-sans text-title-md text-on-surface">Recent Index Jobs</h3>
            <span className="font-mono text-label-caps text-outline uppercase">SQLite-backed</span>
          </div>
          <div className="grid gap-3 overflow-auto pr-1">
            {recentJobs && recentJobs.length > 0 ? recentJobs.map((recentJob) => (
              <RecentJobCard
                key={recentJob.job_id}
                job={recentJob}
                onOpen={() => openIndexJob({
                  jobId: recentJob.job_id,
                  title: recentJob.title,
                  path: recentJob.path,
                  repoName: recentJob.repo_name,
                  sourceKind: recentJob.source_kind,
                  dryRun: recentJob.dry_run,
                  profile: recentJob.profile,
                  includeLanguages: recentJob.include_languages,
                  includePaths: recentJob.include_paths,
                  excludePaths: recentJob.exclude_paths,
                })}
              />
            )) : (
              <div className="rounded-lg border border-dashed border-outline-variant/30 bg-surface-container-high/30 p-4 text-sm text-on-surface-variant">
                No persisted index jobs yet.
              </div>
            )}
          </div>
        </GlassPanel>
      </div>
    )
  }

  const sourceLabel = activeIndexJob.sourceKind ?? job?.source_kind ?? 'path'
  const profileLabel = activeIndexJob.profile ?? job?.profile ?? 'curated'
  const includeLanguages = activeIndexJob.includeLanguages ?? job?.include_languages ?? []
  const includePaths = activeIndexJob.includePaths ?? job?.include_paths ?? []
  const excludePaths = activeIndexJob.excludePaths ?? job?.exclude_paths ?? []
  const isComplete = job?.status === 'completed' || job?.status === 'completed_with_errors'
  const [pipelineExpanded, setPipelineExpanded] = useState(!isComplete)
  const [logsExpanded, setLogsExpanded] = useState(false)
  const [discoveryExpanded, setDiscoveryExpanded] = useState(false)

  return (
    <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-3 pb-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-4 px-1">
        <div className="flex items-center gap-3 min-w-0">
          <span className="material-symbols-outlined text-secondary text-[22px] flex-shrink-0">deployed_code</span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-sans text-title-md font-semibold text-on-surface truncate">{activeIndexJob.title}</h2>
              <span className="rounded bg-surface-container-high px-1.5 py-0.5 text-[9px] uppercase text-on-surface-variant">{sourceLabel}</span>
              <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[9px] uppercase text-primary">{profileLabel}</span>
              {activeIndexJob.dryRun && (
                <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[9px] uppercase text-secondary">dry run</span>
              )}
              {includeLanguages.length > 0 && (
                <span className="rounded bg-tertiary/15 px-1.5 py-0.5 text-[9px] uppercase text-tertiary">lang: {includeLanguages.join(', ')}</span>
              )}
              {includePaths.length > 0 && (
                <span className="rounded bg-surface-container-high px-1.5 py-0.5 text-[9px] uppercase text-on-surface-variant">include: {includePaths.join(', ')}</span>
              )}
              {excludePaths.length > 0 && (
                <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[9px] uppercase text-secondary">exclude: {excludePaths.join(', ')}</span>
              )}
            </div>
            <p className="mt-0.5 truncate text-[11px] text-on-surface-variant">{activeIndexJob.path}</p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-outline-variant/30 bg-surface-container-high px-2.5 py-1">
            <span className={`h-2 w-2 rounded-full ${statusDotClass(job?.status)}`} />
            <span className="font-mono text-[9px] text-on-surface uppercase">{statusLabel}</span>
          </div>
          <button
            type="button"
            onClick={() => setActiveView('explorer')}
            className="px-2.5 py-1 rounded border border-outline-variant/30 text-on-surface font-mono text-[9px] uppercase hover:border-primary/40 transition-colors"
          >
            Back to Explorer
          </button>
          <button
            type="button"
            onClick={() => { clearActiveIndexJob(); setActiveView('explorer') }}
            className="px-2.5 py-1 rounded bg-surface-container-high text-on-surface-variant font-mono text-[9px] uppercase hover:bg-surface-container-highest transition-colors"
          >
            Clear
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded border border-secondary/40 bg-secondary/10 px-3 py-2 text-xs text-secondary">
          {error}
        </div>
      )}

      {/* ── Pipeline (collapsible) ── */}
      <CollapsibleSection
        title="Pipeline"
        summary={!pipelineExpanded ? `${stats.files_scanned} files · ${stats.chunks_extracted} chunks · ${stats.patterns_stored} stored` : undefined}
        badge={stats.current_stage}
        expanded={pipelineExpanded}
        onToggle={() => setPipelineExpanded((v) => !v)}
      >
        <div className="space-y-2">
          <div className="grid gap-2 grid-cols-4">
            {STAGES.map((stage) => (
              <StageCard
                key={stage.id}
                label={stage.label}
                icon={stage.icon}
                active={isStageActive(stage.id, stats.current_stage)}
                complete={isStageComplete(stage.id, stats.current_stage, job?.status ?? 'queued')}
              />
            ))}
          </div>
          <div className="grid gap-2 grid-cols-5">
            <MetricCard label="Files Found" value={stats.files_discovered} />
            <MetricCard label="Scanned" value={stats.files_scanned} />
            <MetricCard label="Chunks" value={stats.chunks_extracted} />
            <MetricCard label="Stored" value={stats.patterns_stored} />
            <MetricCard label="Rejected" value={stats.patterns_rejected ?? 0} />
          </div>
        </div>
      </CollapsibleSection>

      {/* ── Ingestion Logs (collapsible) ── */}
      <CollapsibleSection
        title="Ingestion Logs"
        summary={`${logs.length} entries`}
        badge={activeIndexJob.dryRun ? 'dry run' : 'full index'}
        expanded={logsExpanded}
        onToggle={() => setLogsExpanded((v) => !v)}
      >
        <div
          ref={logViewportRef}
          className="overflow-auto rounded border border-outline-variant/15 bg-black/20 p-3 font-mono text-[11px] leading-5 text-on-surface max-h-[200px]"
        >
          {logs.length > 0 ? (
            <pre className="whitespace-pre-wrap break-words">{logs.join('\n')}</pre>
          ) : (
            <span className="text-on-surface-variant">No logs available.</span>
          )}
        </div>
      </CollapsibleSection>

      {/* ── Discovery Feed (collapsible) ── */}
      {discoveries.length > 0 && (
        <CollapsibleSection
          title="Discovery Feed"
          summary={`${discoveries.length} patterns found`}
          expanded={discoveryExpanded}
          onToggle={() => setDiscoveryExpanded((v) => !v)}
        >
          <div className="overflow-y-auto max-h-48 space-y-1.5">
            {discoveries.map((event, index) => (
              <div key={`${event.name}-${index}`} className="flex items-center justify-between gap-3 rounded bg-surface-container-high/40 px-3 py-2">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-on-surface truncate">{event.name}</p>
                  {event.message && <p className="text-[10px] text-on-surface-variant truncate">{event.message}</p>}
                </div>
                <span className="rounded bg-primary/15 px-1.5 py-0.5 text-[9px] uppercase text-primary flex-shrink-0">{event.category}</span>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* ── Repo Patterns ── */}
      {!activeIndexJob.dryRun && (job?.repo_name ?? activeIndexJob.repoName) && (
        <RepoPatternList repoName={(job?.repo_name ?? activeIndexJob.repoName)!} />
      )}
    </div>
  )
}

function RecentJobCard({ job, onOpen }: { job: WorkspaceIndexJob; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="rounded-lg border border-outline-variant/20 bg-surface-container-high/50 p-4 text-left hover:border-primary/30 transition-colors"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-medium text-on-surface">{job.title}</p>
            <span className="rounded bg-surface-container-highest px-2 py-0.5 text-[10px] uppercase text-on-surface-variant">{job.source_kind}</span>
            <span className="rounded bg-primary/15 px-2 py-0.5 text-[10px] uppercase text-primary">{job.profile}</span>
            {job.include_languages.length > 0 && (
              <span className="rounded bg-tertiary/15 px-2 py-0.5 text-[10px] uppercase text-tertiary">{job.include_languages.join(', ')}</span>
            )}
            {job.dry_run && <span className="rounded bg-secondary/15 px-2 py-0.5 text-[10px] uppercase text-secondary">dry run</span>}
          </div>
          <p className="mt-1 truncate text-[11px] text-outline">{job.path}</p>
          {(job.include_paths.length > 0 || job.exclude_paths.length > 0) && (
            <p className="mt-1 truncate text-[10px] text-on-surface-variant">
              {job.include_paths.length > 0 ? `include ${job.include_paths.join(', ')}` : ''}
              {job.include_paths.length > 0 && job.exclude_paths.length > 0 ? ' · ' : ''}
              {job.exclude_paths.length > 0 ? `exclude ${job.exclude_paths.join(', ')}` : ''}
            </p>
          )}
        </div>
        <span className={`font-mono text-[10px] uppercase ${statusTextClass(job.status)}`}>
          {job.status}
        </span>
      </div>
      <p className="mt-2 text-[11px] text-on-surface-variant">Updated {new Date(job.updated_at * 1000).toLocaleString()}</p>
    </button>
  )
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded border border-outline-variant/15 bg-surface-container-lowest/40 px-3 py-2">
      <p className="text-lg font-semibold text-on-surface">{value}</p>
      <p className="font-mono text-[9px] text-on-surface-variant uppercase">{label}</p>
    </div>
  )
}

function CollapsibleSection({
  title,
  summary,
  badge,
  expanded,
  onToggle,
  children,
}: {
  title: string
  summary?: string
  badge?: string
  expanded: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-outline-variant/20 bg-surface-container/60">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center justify-between gap-4 w-full text-left px-4 py-2.5"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={`material-symbols-outlined text-[14px] text-outline transition-transform ${expanded ? 'rotate-0' : '-rotate-90'}`}>
            expand_more
          </span>
          <span className="text-sm font-medium text-on-surface">{title}</span>
          {summary && <span className="text-[11px] text-on-surface-variant truncate">{summary}</span>}
        </div>
        {badge && <span className="font-mono text-[9px] text-outline uppercase flex-shrink-0">{badge}</span>}
      </button>
      {expanded && (
        <div className="px-4 pb-3 pt-0">
          {children}
        </div>
      )}
    </div>
  )
}

function StageCard({
  label,
  icon,
  active,
  complete,
}: {
  label: string
  icon: string
  active: boolean
  complete: boolean
}) {
  return (
    <div className={`rounded border px-3 py-2 transition-colors ${complete ? 'border-primary/30 bg-primary/8' : active ? 'border-secondary/30 bg-secondary/8' : 'border-outline-variant/15 bg-surface-container-lowest/30'}`}>
      <div className="flex items-center gap-2">
        <span className={`material-symbols-outlined text-[16px] ${complete ? 'text-primary' : active ? 'text-secondary' : 'text-outline'}`}>
          {complete ? 'task_alt' : icon}
        </span>
        <p className="text-xs font-medium text-on-surface">{label}</p>
      </div>
    </div>
  )
}

function isStageActive(stageId: string, currentStage: string): boolean {
  return stageId === currentStage
}

function isStageComplete(stageId: string, currentStage: string, status: string): boolean {
  const order = ['queued', 'scan', 'extract', 'store', 'complete']
  if (status === 'completed' || status === 'completed_with_errors') {
    return stageId !== 'queued'
  }
  return order.indexOf(stageId) !== -1 && order.indexOf(stageId) < order.indexOf(currentStage)
}

function statusDotClass(status?: WorkspaceIndexJob['status']): string {
  if (status === 'running') return 'bg-tertiary animate-pulse'
  if (status === 'failed') return 'bg-secondary'
  if (status === 'completed_with_errors') return 'bg-secondary'
  return 'bg-primary'
}

function statusTextClass(status: WorkspaceIndexJob['status']): string {
  if (status === 'running') return 'text-tertiary'
  if (status === 'failed' || status === 'completed_with_errors') return 'text-secondary'
  return 'text-primary'
}

const CATEGORY_COLORS: Record<string, string> = {
  design_pattern: 'bg-primary/15 text-primary',
  resilience: 'bg-tertiary/15 text-tertiary',
  api_pattern: 'bg-secondary/20 text-secondary',
  data_access: 'bg-primary/20 text-primary',
  async_pattern: 'bg-tertiary/20 text-tertiary',
  config: 'bg-outline/20 text-on-surface-variant',
  testing: 'bg-secondary/15 text-secondary',
  utility: 'bg-outline/15 text-on-surface-variant',
  security: 'bg-secondary/25 text-secondary',
  general: 'bg-surface-container-highest text-on-surface-variant',
}

function RepoPatternList({ repoName }: { repoName: string }) {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState(true)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const { data: patterns, isLoading } = useQuery({
    queryKey: ['repo-patterns', repoName],
    queryFn: () => api.patterns.list(500, repoName),
    enabled: !!repoName,
    staleTime: 10_000,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.patterns.delete(id),
    onMutate: (id) => setDeletingId(id),
    onSettled: () => setDeletingId(null),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['repo-patterns', repoName] })
    },
  })

  const filtered = (patterns ?? []).filter((p) =>
    !search ||
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.category.toLowerCase().includes(search.toLowerCase()) ||
    p.language.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="rounded-lg border border-outline-variant/20 bg-surface-container/60 flex flex-col">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center justify-between gap-4 w-full text-left px-4 py-2.5"
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className={`material-symbols-outlined text-[14px] text-outline transition-transform ${expanded ? 'rotate-0' : '-rotate-90'}`}>
            expand_more
          </span>
          <span className="text-sm font-medium text-on-surface">Repo Patterns</span>
          <span className="text-[11px] text-on-surface-variant">
            {isLoading ? 'Loading…' : `${filtered.length} of ${patterns?.length ?? 0} stored`}
          </span>
        </div>
        <span className="font-mono text-[9px] text-outline uppercase flex-shrink-0">{repoName}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-0 flex flex-col gap-3">
          <div className="flex items-center">
            <input
              type="text"
              placeholder="Filter by name, category, language…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="rounded border border-outline-variant/30 bg-surface-container-high px-3 py-1.5 text-xs text-on-surface placeholder:text-outline focus:outline-none focus:border-primary/50 w-64"
            />
          </div>

          <div className="overflow-auto max-h-[600px] pr-1">
            {isLoading ? (
              <div className="flex items-center justify-center py-8 text-sm text-on-surface-variant">
                <span className="material-symbols-outlined text-[18px] mr-2 animate-spin">progress_activity</span>
                Loading patterns…
              </div>
            ) : filtered.length === 0 ? (
              <div className="rounded-lg border border-dashed border-outline-variant/30 bg-surface-container-high/30 p-6 text-sm text-on-surface-variant text-center">
                {search ? 'No patterns match this filter.' : 'No patterns found for this repo.'}
              </div>
            ) : (
              <div className="grid gap-2">
                {filtered.map((pattern) => (
                  <PatternRow
                    key={pattern.id}
                    pattern={pattern}
                    deleting={deletingId === pattern.id}
                    onDelete={() => deleteMutation.mutate(pattern.id)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function PatternRow({
  pattern,
  deleting,
  onDelete,
}: {
  pattern: Pattern
  deleting: boolean
  onDelete: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const categoryColor = CATEGORY_COLORS[pattern.category] ?? 'bg-surface-container-highest text-on-surface-variant'

  const handleDeleteClick = () => {
    if (confirming) {
      onDelete()
      setConfirming(false)
    } else {
      setConfirming(true)
    }
  }

  return (
    <div className={`flex items-start gap-3 rounded-lg border border-outline-variant/20 bg-surface-container-high/50 px-4 py-3 transition-opacity ${deleting ? 'opacity-40 pointer-events-none' : ''}`}>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-on-surface">{pattern.name}</p>
          <span className={`rounded px-2 py-0.5 text-[10px] uppercase font-mono flex-shrink-0 ${categoryColor}`}>{pattern.category}</span>
          {pattern.language && pattern.language !== 'unknown' && (
            <span className="rounded bg-surface-container-highest px-2 py-0.5 text-[10px] uppercase text-on-surface-variant flex-shrink-0">{pattern.language}</span>
          )}
        </div>
        {pattern.summary && (
          <p className="mt-1.5 text-xs text-on-surface-variant line-clamp-2">{pattern.summary}</p>
        )}
        {pattern.source_file && (
          <p className="mt-1 text-[10px] text-outline truncate">{pattern.source_file}</p>
        )}
      </div>
      <button
        type="button"
        onClick={handleDeleteClick}
        onBlur={() => setConfirming(false)}
        disabled={deleting}
        className={`flex-shrink-0 flex items-center gap-1 rounded px-2 py-1.5 text-[11px] font-mono uppercase transition-colors ${confirming ? 'bg-secondary/20 text-secondary border border-secondary/40' : 'text-outline hover:text-secondary hover:bg-secondary/10'}`}
        title={confirming ? 'Click again to confirm deletion' : 'Delete pattern'}
      >
        <span className="material-symbols-outlined text-[14px]">{confirming ? 'warning' : 'delete'}</span>
        {confirming ? 'Confirm' : ''}
      </button>
    </div>
  )
}
