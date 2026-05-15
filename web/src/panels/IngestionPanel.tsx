import { useEffect, useMemo, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type WorkspaceIndexJob } from '@/api/client'
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
  const setActiveIndexJob = useUIStore((s) => s.setActiveIndexJob)
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
    current_stage: 'queued',
  }

  const statusLabel = useMemo(() => {
    if (!job) return 'Preparing'
    if (job.status === 'completed') return job.dry_run ? 'Dry Run Complete' : 'Index Complete'
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
                onOpen={() => setActiveIndexJob({
                  jobId: recentJob.job_id,
                  title: recentJob.title,
                  path: recentJob.path,
                  repoName: recentJob.repo_name,
                  sourceKind: recentJob.source_kind,
                  dryRun: recentJob.dry_run,
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

  const latestLog = logs[logs.length - 1]
  const sourceLabel = activeIndexJob.sourceKind ?? job?.source_kind ?? 'path'

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-6">
      <GlassPanel className="p-6 flex flex-col gap-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined text-secondary text-[28px]">deployed_code</span>
              <h2 className="font-sans text-headline-md font-semibold text-on-surface">Ingest Repository</h2>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-sans text-headline-sm text-on-surface">{activeIndexJob.title}</p>
              <span className="rounded bg-surface-container-high px-2 py-1 text-[10px] uppercase text-on-surface-variant">{sourceLabel}</span>
              {activeIndexJob.dryRun && (
                <span className="rounded bg-secondary/15 px-2 py-1 text-[10px] uppercase text-secondary">dry run</span>
              )}
            </div>
            <p className="max-w-3xl truncate text-sm text-on-surface-variant">{activeIndexJob.path}</p>
            {latestLog && (
              <p className="max-w-3xl text-xs text-outline">Latest: {latestLog}</p>
            )}
          </div>

          <div className="flex flex-col items-start gap-3 lg:items-end">
            <div className="inline-flex items-center gap-2 rounded-full border border-outline-variant/30 bg-surface-container-high px-3 py-1.5">
              <span className={`h-2.5 w-2.5 rounded-full ${job?.status === 'running' ? 'bg-tertiary animate-pulse' : job?.status === 'failed' ? 'bg-secondary' : 'bg-primary'}`} />
              <span className="font-mono text-label-caps text-on-surface uppercase">{statusLabel}</span>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setActiveView('explorer')}
                className="px-3 py-2 rounded border border-outline-variant/30 text-on-surface font-mono text-[11px] uppercase"
              >
                Back to Explorer
              </button>
              <button
                type="button"
                onClick={() => {
                  clearActiveIndexJob()
                  setActiveView('explorer')
                }}
                className="px-3 py-2 rounded bg-surface-container-high text-on-surface-variant font-mono text-[11px] uppercase"
              >
                Clear
              </button>
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded border border-secondary/40 bg-secondary/10 px-4 py-3 text-sm text-secondary">
            {error}
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-lg border border-outline-variant/20 bg-surface-container-high/60 p-5">
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-sans text-title-md text-on-surface">Pipeline</h3>
              <span className="font-mono text-label-caps text-outline uppercase">
                {stats.current_stage}
              </span>
            </div>
            <div className="mt-6 grid gap-4 md:grid-cols-4">
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

            <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="Files Found" value={stats.files_discovered} />
              <MetricCard label="Files Scanned" value={stats.files_scanned} />
              <MetricCard label="Chunks Extracted" value={stats.chunks_extracted} />
              <MetricCard label="Patterns Stored" value={stats.patterns_stored} />
            </div>
          </div>

          <GlassPanel className="p-5 min-h-0 flex flex-col gap-4 overflow-hidden">
            <div className="flex items-center justify-between gap-4">
              <h3 className="font-sans text-title-md text-on-surface">Discovery Feed</h3>
              <span className="font-mono text-label-caps text-outline uppercase">{discoveries.length} recent</span>
            </div>
            <div className="grid gap-3 overflow-auto pr-1">
              {discoveries.length > 0 ? discoveries.map((event, index) => (
                <div key={`${event.name}-${index}`} className="rounded-lg border border-outline-variant/20 bg-surface-container-high/60 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-[11px] uppercase tracking-wide text-secondary">Found Pattern</span>
                    <span className="rounded bg-primary/15 px-2 py-1 text-[10px] uppercase tracking-wide text-primary">{event.category}</span>
                  </div>
                  <p className="mt-3 text-sm font-medium text-on-surface">{event.name}</p>
                  <p className="mt-1 text-xs text-on-surface-variant">{event.message}</p>
                </div>
              )) : (
                <div className="rounded-lg border border-dashed border-outline-variant/30 bg-surface-container-high/30 p-4 text-sm text-on-surface-variant">
                  Pattern discoveries will appear here as the extractor stores them.
                </div>
              )}
            </div>
          </GlassPanel>
        </div>
      </GlassPanel>

      <GlassPanel className="min-h-0 flex-1 p-5 flex flex-col gap-4 overflow-hidden">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="font-sans text-title-md text-on-surface">Ingestion Logs</h3>
            <p className="text-sm text-on-surface-variant">Live progress from scan, chunking, extraction, and storage.</p>
          </div>
          <span className="font-mono text-label-caps text-outline uppercase">
            {activeIndexJob.dryRun ? 'dry run' : 'full index'}
          </span>
        </div>

        <div
          ref={logViewportRef}
          className="min-h-0 flex-1 overflow-auto rounded-lg border border-outline-variant/20 bg-black/30 p-4 font-mono text-xs leading-6 text-on-surface"
        >
          {logs.length > 0 ? (
            <pre className="whitespace-pre-wrap break-words">{logs.join('\n')}</pre>
          ) : (
            <div className="text-on-surface-variant">Waiting for ingestion output...</div>
          )}
        </div>
      </GlassPanel>
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
            {job.dry_run && <span className="rounded bg-secondary/15 px-2 py-0.5 text-[10px] uppercase text-secondary">dry run</span>}
          </div>
          <p className="mt-1 truncate text-[11px] text-outline">{job.path}</p>
        </div>
        <span className={`font-mono text-[10px] uppercase ${job.status === 'running' ? 'text-tertiary' : job.status === 'failed' ? 'text-secondary' : 'text-primary'}`}>
          {job.status}
        </span>
      </div>
      <p className="mt-2 text-[11px] text-on-surface-variant">Updated {new Date(job.updated_at * 1000).toLocaleString()}</p>
    </button>
  )
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-outline-variant/20 bg-surface-container-lowest/50 p-4">
      <p className="text-2xl font-semibold text-on-surface">{value}</p>
      <p className="mt-1 font-mono text-label-caps text-on-surface-variant uppercase">{label}</p>
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
    <div className={`rounded-lg border p-4 transition-colors ${complete ? 'border-primary/40 bg-primary/10' : active ? 'border-secondary/40 bg-secondary/10' : 'border-outline-variant/20 bg-surface-container-lowest/40'}`}>
      <div className="flex items-center justify-between gap-3">
        <span className={`material-symbols-outlined text-[20px] ${complete ? 'text-primary' : active ? 'text-secondary' : 'text-outline'}`}>
          {icon}
        </span>
        {complete && <span className="material-symbols-outlined text-[16px] text-primary">task_alt</span>}
      </div>
      <p className="mt-3 text-sm font-medium text-on-surface">{label}</p>
    </div>
  )
}

function isStageActive(stageId: string, currentStage: string): boolean {
  return stageId === currentStage
}

function isStageComplete(stageId: string, currentStage: string, status: string): boolean {
  const order = ['queued', 'scan', 'extract', 'store', 'complete']
  if (status === 'completed') {
    return stageId !== 'queued'
  }
  return order.indexOf(stageId) !== -1 && order.indexOf(stageId) < order.indexOf(currentStage)
}
