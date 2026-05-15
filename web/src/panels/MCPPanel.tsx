import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type MCPToolInfo } from '@/api/client'
import { GlassPanel } from '@/components/GlassPanel'

type LogEvent = {
  type: 'log'
  line: string
}

export function MCPPanel() {
  const queryClient = useQueryClient()
  const logViewportRef = useRef<HTMLDivElement | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [streamError, setStreamError] = useState<string | null>(null)

  const statusQuery = useQuery({
    queryKey: ['mcp-status'],
    queryFn: api.mcp.status,
    refetchInterval: 5000,
  })
  const toolsQuery = useQuery({
    queryKey: ['mcp-tools'],
    queryFn: api.mcp.tools,
  })

  const startMutation = useMutation({
    mutationFn: api.mcp.start,
    onSuccess: () => {
      setStreamError(null)
      void queryClient.invalidateQueries({ queryKey: ['mcp-status'] })
    },
  })
  const stopMutation = useMutation({
    mutationFn: api.mcp.stop,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['mcp-status'] })
    },
  })

  useEffect(() => {
    const source = new EventSource('/api/mcp/logs/stream')

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as LogEvent
        if (payload.type === 'log') {
          setLogs((current) => {
            const next = [...current, payload.line]
            return next.slice(-500)
          })
        }
      } catch {
        setStreamError('Failed to decode MCP monitor log event.')
      }
    }

    source.onerror = () => {
      setStreamError('MCP log stream disconnected. The backend may be restarting.')
      source.close()
    }

    return () => {
      source.close()
    }
  }, [])

  useEffect(() => {
    const viewport = logViewportRef.current
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight
    }
  }, [logs])

  const tools = toolsQuery.data?.tools ?? []
  const status = statusQuery.data
  const busy = startMutation.isPending || stopMutation.isPending
  const endpoint = useMemo(() => {
    if (!status) return 'http://127.0.0.1:8002/mcp'
    return `http://${status.host}:${status.port}/mcp`
  }, [status])

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-6">
      <GlassPanel className="p-6 flex flex-col gap-6 overflow-hidden">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined text-primary text-[28px]">monitoring</span>
              <h2 className="font-sans text-headline-md font-semibold text-on-surface">MCP Monitor</h2>
            </div>
            <p className="text-sm text-on-surface-variant max-w-3xl">
              This panel controls a separate HTTP MCP instance for observability. Claude Code still uses the stdio server from .mcp.json, which is not directly visible here.
            </p>
          </div>

          <div className="flex flex-col items-start gap-3 lg:items-end">
            <StatusBadge running={Boolean(status?.running)} />
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => startMutation.mutate()}
                disabled={busy || Boolean(status?.running)}
                className="px-4 py-2 rounded bg-primary text-on-primary disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Start HTTP MCP
              </button>
              <button
                type="button"
                onClick={() => stopMutation.mutate()}
                disabled={busy || !status?.running}
                className="px-4 py-2 rounded border border-outline-variant/30 text-on-surface disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Stop
              </button>
            </div>
          </div>
        </div>

        {(startMutation.error || stopMutation.error || statusQuery.error || streamError) && (
          <div className="rounded border border-secondary/40 bg-secondary/10 px-4 py-3 text-sm text-secondary">
            {formatError(startMutation.error ?? stopMutation.error ?? statusQuery.error) ?? streamError}
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-4">
          <InfoCard label="Transport" value="streamable-http" />
          <InfoCard label="Endpoint" value={endpoint} />
          <InfoCard label="PID" value={status?.pid ? String(status.pid) : 'Not running'} />
          <InfoCard label="Uptime" value={status?.uptime_seconds ? `${status.uptime_seconds}s` : 'Idle'} />
        </div>
      </GlassPanel>

      <div className="grid min-h-0 flex-1 gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <GlassPanel className="p-6 min-h-0 flex flex-col gap-4 overflow-hidden">
          <div className="flex items-center justify-between gap-4">
            <h3 className="font-mono text-label-caps text-on-surface-variant uppercase">Monitor Logs</h3>
            <span className="text-xs text-outline">Buffer: last 500 lines</span>
          </div>
          <div
            ref={logViewportRef}
            className="min-h-0 flex-1 overflow-auto rounded border border-outline-variant/20 bg-black/30 p-4 font-mono text-xs leading-6 text-on-surface"
          >
            {logs.length > 0 ? (
              <pre className="whitespace-pre-wrap break-words">{logs.join('\n')}</pre>
            ) : (
              <div className="text-on-surface-variant">No monitor output yet.</div>
            )}
          </div>
        </GlassPanel>

        <GlassPanel className="p-6 min-h-0 flex flex-col gap-4 overflow-hidden">
          <div className="flex items-center justify-between gap-4">
            <h3 className="font-mono text-label-caps text-on-surface-variant uppercase">Tool Inventory</h3>
            <span className="text-xs text-outline">{tools.length} tools</span>
          </div>
          <div className="grid gap-3 overflow-auto pr-1">
            {tools.map((tool) => (
              <ToolCard key={tool.name} tool={tool} />
            ))}
          </div>
        </GlassPanel>
      </div>
    </div>
  )
}

function StatusBadge({ running }: { running: boolean }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-outline-variant/30 bg-surface-container-high px-3 py-1.5">
      <span className={`h-2.5 w-2.5 rounded-full ${running ? 'bg-tertiary animate-pulse' : 'bg-secondary'}`} />
      <span className="font-mono text-label-caps text-on-surface uppercase">
        {running ? 'HTTP monitor live' : 'HTTP monitor idle'}
      </span>
    </div>
  )
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-outline-variant/20 bg-surface-container-high/60 p-4">
      <p className="font-mono text-label-caps text-on-surface-variant uppercase">{label}</p>
      <p className="mt-2 break-all text-sm text-on-surface">{value}</p>
    </div>
  )
}

function ToolCard({ tool }: { tool: MCPToolInfo }) {
  return (
    <div className="rounded-lg border border-outline-variant/20 bg-surface-container-high/60 p-4">
      <div className="flex items-center justify-between gap-4">
        <p className="font-mono text-sm text-on-surface">{tool.name}</p>
        <span className={`rounded px-2 py-1 text-[10px] uppercase tracking-wide ${tool.mode === 'write' ? 'bg-secondary/15 text-secondary' : 'bg-primary/15 text-primary'}`}>
          {tool.mode}
        </span>
      </div>
      <p className="mt-2 text-sm text-on-surface-variant">{tool.description}</p>
    </div>
  )
}

function formatError(error: unknown): string | null {
  if (!error) {
    return null
  }
  if (typeof error === 'string') {
    return error
  }
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Unknown MCP monitor error.'
}
