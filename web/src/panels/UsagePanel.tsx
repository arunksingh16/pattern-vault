import { useState } from 'react'
import { useDailyUsage } from '@/api/hooks/useUsage'

export function UsagePanel() {
  const [days, setDays] = useState(14)
  const { data, isLoading } = useDailyUsage(days)

  const totals = (data ?? []).reduce(
    (acc, row) => {
      acc.requests += row.requests
      acc.input += row.input_tokens
      acc.output += row.output_tokens
      acc.total += row.total_tokens
      acc.estimated += row.estimated_requests
      return acc
    },
    { requests: 0, input: 0, output: 0, total: 0, estimated: 0 }
  )

  return (
    <div className="flex-1 glass-panel p-6 flex flex-col gap-6 overflow-auto">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-secondary text-[28px]">query_stats</span>
          <div>
            <h2 className="font-sans text-headline-md font-semibold text-on-surface">Token Usage</h2>
            <p className="text-sm text-on-surface-variant">
              Daily totals grouped by provider across chat and indexing calls.
            </p>
          </div>
        </div>

        <label className="flex items-center gap-3 text-sm text-on-surface-variant">
          Range
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="bg-surface-container-high border border-outline-variant/30 rounded px-3 py-2 text-on-surface"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={60}>60 days</option>
          </select>
        </label>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-5 gap-4">
        <StatCard label="Requests" value={totals.requests} />
        <StatCard label="Input Tokens" value={totals.input} />
        <StatCard label="Output Tokens" value={totals.output} />
        <StatCard label="Total Tokens" value={totals.total} />
        <StatCard label="Estimated Rows" value={totals.estimated} tone="secondary" />
      </div>

      <div className="rounded-xl border border-outline-variant/20 bg-surface-container-high/40 overflow-hidden">
        <div className="grid grid-cols-[1.2fr_1fr_0.8fr_1fr_1fr_1fr_0.8fr] gap-4 px-4 py-3 border-b border-outline-variant/20 font-mono text-label-caps text-on-surface-variant uppercase">
          <span>Day</span>
          <span>Provider</span>
          <span>Requests</span>
          <span>Input</span>
          <span>Output</span>
          <span>Total</span>
          <span>Estimated</span>
        </div>

        {isLoading && (
          <div className="p-6 text-on-surface-variant">Loading usage…</div>
        )}

        {!isLoading && (!data || data.length === 0) && (
          <div className="p-6 text-on-surface-variant">
            No token usage recorded yet. Usage starts appearing after chat or indexing model calls run through the backend.
          </div>
        )}

        {!isLoading && data && data.map((row) => (
          <div
            key={`${row.day}-${row.provider}`}
            className="grid grid-cols-[1.2fr_1fr_0.8fr_1fr_1fr_1fr_0.8fr] gap-4 px-4 py-3 border-b border-outline-variant/10 text-sm text-on-surface"
          >
            <span>{row.day}</span>
            <span className="capitalize">{row.provider}</span>
            <span>{formatNumber(row.requests)}</span>
            <span>{formatNumber(row.input_tokens)}</span>
            <span>{formatNumber(row.output_tokens)}</span>
            <span className="text-secondary font-semibold">{formatNumber(row.total_tokens)}</span>
            <span>{row.estimated_requests > 0 ? formatNumber(row.estimated_requests) : '0'}</span>
          </div>
        ))}
      </div>

      <p className="text-xs text-on-surface-variant">
        Estimated rows appear when the provider response does not include usage counts. This is most likely with some Ollama-compatible responses and proxy setups.
      </p>
    </div>
  )
}

function StatCard({
  label,
  value,
  tone = 'primary',
}: {
  label: string
  value: number
  tone?: 'primary' | 'secondary'
}) {
  return (
    <div className="p-4 rounded-lg bg-surface-container-high/60 border border-outline-variant/20">
      <p className={tone === 'secondary' ? 'text-2xl font-bold text-secondary' : 'text-2xl font-bold text-primary'}>
        {formatNumber(value)}
      </p>
      <p className="font-mono text-label-caps text-on-surface-variant uppercase mt-1">{label}</p>
    </div>
  )
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US').format(value)
}
