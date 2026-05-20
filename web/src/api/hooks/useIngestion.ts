import { useEffect, useState } from 'react'
import { api, type WorkspaceIndexEvent, type WorkspaceIndexJob } from '@/api/client'

interface UseIngestionResult {
  job: WorkspaceIndexJob | null
  events: WorkspaceIndexEvent[]
  logs: string[]
  discoveries: WorkspaceIndexEvent[]
  error: string | null
}

export function useIngestion(jobId: string | null): UseIngestionResult {
  const [job, setJob] = useState<WorkspaceIndexJob | null>(null)
  const [events, setEvents] = useState<WorkspaceIndexEvent[]>([])
  const [logs, setLogs] = useState<string[]>([])
  const [discoveries, setDiscoveries] = useState<WorkspaceIndexEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId) {
      setJob(null)
      setEvents([])
      setLogs([])
      setDiscoveries([])
      setError(null)
      return
    }

    let closed = false
    setEvents([])
    setLogs([])
    setDiscoveries([])
    setError(null)

    void api.workspace.indexStatus(jobId)
      .then((snapshot) => {
        if (!closed) {
          setJob(snapshot)
          setError(snapshot.error)
        }
      })
      .catch((err) => {
        if (!closed) {
          setError(err instanceof Error ? err.message : 'Failed to load ingestion job status.')
        }
      })

    const source = new EventSource(`/api/workspace/index/${encodeURIComponent(jobId)}/stream`)

    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as WorkspaceIndexEvent
        setEvents((current) => [...current, event].slice(-500))
        if (event.message) {
          setLogs((current) => [...current, event.message as string].slice(-500))
        }
        if (event.type === 'pattern_found') {
          setDiscoveries((current) => [event, ...current].slice(0, 20))
        }

        setJob((current) => {
          if (event.type === 'job_summary' && event.job) {
            return current ? { ...current, ...event.job } : event.job
          }

          if (!current) {
            return current
          }
          const nextStatus =
            event.type === 'done'
              ? event.status ?? (event.errors && event.errors.length > 0 ? 'completed_with_errors' : 'completed')
              : event.type === 'error' && event.recoverable !== true
                ? event.status ?? 'failed'
                : current.status

          return {
            ...current,
            status: nextStatus,
            stats: event.stats ?? current.stats,
            error: event.type === 'error' ? event.message ?? current.error : current.error,
          }
        })

        if (event.type === 'error') {
          setError(event.message ?? 'Index job failed.')
        }
      } catch {
        setError('Failed to decode ingestion event stream.')
      }
    }

    source.onerror = () => {
      source.close()
    }

    return () => {
      closed = true
      source.close()
    }
  }, [jobId])

  return { job, events, logs, discoveries, error }
}
