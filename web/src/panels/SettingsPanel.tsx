import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'

function Row({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start gap-4 py-2.5 border-b border-outline-variant/15 last:border-0">
      <span className="font-mono text-[11px] uppercase text-outline w-44 shrink-0 pt-0.5">{label}</span>
      <span className={`${mono ? 'font-mono' : 'font-sans'} text-sm text-on-surface break-all`}>{value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <h3 className="font-mono text-label-caps text-outline uppercase mb-3">{title}</h3>
      <div className="bg-surface-container-lowest border border-outline-variant/20 rounded-lg px-4 divide-y divide-outline-variant/10">
        {children}
      </div>
    </div>
  )
}

export function SettingsPanel() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
  })
  const { data: stats } = useQuery({
    queryKey: ['vault-stats'],
    queryFn: api.stats,
  })
  const { data: roots } = useQuery({
    queryKey: ['workspace-roots'],
    queryFn: api.workspace.roots,
  })
  const { data: cloned } = useQuery({
    queryKey: ['cloned-repos'],
    queryFn: api.workspace.cloned,
  })

  // Derive clone base dir from first cloned repo's local_path (strip owner/repo suffix)
  const cloneBaseDir = (() => {
    if (!cloned || cloned.length === 0) return null
    const first = cloned[0]
    const suffix = `/${first.owner}/${first.repo}`
    return first.local_path.endsWith(suffix)
      ? first.local_path.slice(0, -suffix.length)
      : null
  })()

  return (
    <div className="flex-1 glass-panel p-6 flex flex-col gap-6 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="material-symbols-outlined text-primary text-[28px]">settings</span>
        <h2 className="font-sans text-headline-md font-semibold text-on-surface">Settings</h2>
        <span className="text-[11px] font-mono text-outline ml-2">(read-only — set via env vars)</span>
      </div>

      {/* Backend */}
      <Section title="Backend / Model">
        <Row label="Backend" value={health?.backend ?? '—'} />
        <Row label="Status" value={health?.status ?? '—'} />
      </Section>

      {/* Database */}
      <Section title="Database">
        <Row label="DB Path" value={health?.db_path ?? '—'} />
        <Row label="Patterns" value={stats ? String(stats.patterns) : '—'} />
        <Row label="Chunks" value={stats ? String(stats.chunks) : '—'} />
        <Row label="Insights" value={stats ? String(stats.insights) : '—'} />
        <Row label="Languages" value={stats?.languages?.join(', ') || '—'} />
        <Row label="Categories" value={stats?.categories?.join(', ') || '—'} />
      </Section>

      {/* Workspace roots */}
      <Section title="Workspace Roots">
        {roots && roots.length > 0 ? (
          roots.map((r) => (
            <Row key={r.path} label={r.name} value={r.path} />
          ))
        ) : (
          <Row label="roots" value="None configured — set PATTERN_VAULT_WORKSPACE_ROOTS" />
        )}
      </Section>

      {/* Clone cache */}
      <Section title="Cloned Repo Cache">
        <Row label="Clone base dir" value={cloneBaseDir ?? (cloned && cloned.length === 0 ? 'No repos cloned yet' : '—')} />
        <Row label="Repos registered" value={cloned ? String(cloned.length) : '—'} />
        {cloned && cloned.length > 0 && (
          <div className="py-2.5">
            <span className="font-mono text-[11px] uppercase text-outline block mb-2">Cloned repos</span>
            <div className="space-y-1">
              {cloned.map((repo) => (
                <div key={repo.id} className="flex items-center gap-3">
                  <span className="material-symbols-outlined text-[14px] text-primary">code</span>
                  <span className="font-mono text-sm text-on-surface">{repo.owner}/{repo.repo}</span>
                  <span className="font-mono text-[10px] text-outline">{repo.branch}</span>
                  <span className="font-mono text-[10px] text-outline ml-auto truncate max-w-xs">{repo.local_path}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* Environment variable reference */}
      <Section title="Environment Variables">
        <Row label="PATTERN_VAULT_BACKEND" value="anthropic | bedrock | bifrost | ollama" />
        <Row label="PATTERN_VAULT_DB" value="~/.pattern-vault/patterns.db (default)" />
        <Row label="PATTERN_VAULT_WORKSPACE_ROOTS" value="os.pathsep-separated paths agents may scan" />
        <Row label="PATTERN_VAULT_MODEL" value="Override model ID per backend" />
        <Row label="ANTHROPIC_API_KEY" value="Required if backend=anthropic" />
        <Row label="AWS_ACCESS_KEY_ID / SECRET" value="Required if backend=bedrock" />
        <Row label="BIFROST_URL" value="Required if backend=bifrost (e.g. http://localhost:8080/anthropic)" />
        <Row label="OLLAMA_BASE_URL" value="http://localhost:11434/v1 (default)" />
      </Section>
    </div>
  )
}
