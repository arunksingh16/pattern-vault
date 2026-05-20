import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

export function VaultPanel() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: api.stats,
  })

  return (
    <div className="flex-1 glass-panel p-6 flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <span className="material-symbols-outlined text-primary text-[28px]">inventory_2</span>
        <h2 className="font-sans text-headline-md font-semibold text-on-surface">Vault Overview</h2>
      </div>

      {stats ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="Patterns" value={stats.patterns} color="primary" />
          <StatCard label="Chunks" value={stats.chunks} color="secondary" />
          <StatCard label="Insights" value={stats.insights} color="tertiary" />
          <StatCard label="Languages" value={stats.languages.length} color="primary" />
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 rounded-lg bg-surface-container-high/50 animate-pulse" />
          ))}
        </div>
      )}

      {stats && stats.categories.length > 0 && (
        <div>
          <h3 className="font-mono text-label-caps text-on-surface-variant uppercase mb-3">Categories</h3>
          <div className="flex flex-wrap gap-2">
            {stats.categories.map((cat) => (
              <span key={cat} className="px-2 py-1 text-xs rounded bg-surface-container-highest text-on-surface-variant border border-outline-variant/20">
                {cat}
              </span>
            ))}
          </div>
        </div>
      )}

      {stats && stats.languages.length > 0 && (
        <div>
          <h3 className="font-mono text-label-caps text-on-surface-variant uppercase mb-3">Languages</h3>
          <div className="flex flex-wrap gap-2">
            {stats.languages.map((lang) => (
              <span key={lang} className="px-2 py-1 text-xs rounded bg-surface-container-highest text-on-surface-variant border border-outline-variant/20">
                {lang}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="p-4 rounded-lg bg-surface-container-high/60 border border-outline-variant/20">
      <p className={`text-2xl font-bold text-${color}`}>{value}</p>
      <p className="font-mono text-label-caps text-on-surface-variant uppercase mt-1">{label}</p>
    </div>
  )
}
