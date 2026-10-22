import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type ConnectionResult, type SettingField, type SettingsResponse } from '@/api/client'

type Backend = 'ollama' | 'anthropic' | 'bedrock' | 'bifrost'

const BACKENDS: { id: Backend; label: string }[] = [
  { id: 'ollama', label: 'Ollama (local)' },
  { id: 'anthropic', label: 'Anthropic API' },
  { id: 'bedrock', label: 'Amazon Bedrock' },
  { id: 'bifrost', label: 'Bifrost proxy' },
]

const BACKEND_FIELDS: Record<Backend, string[]> = {
  ollama: ['ollama.base_url', 'model.model'],
  anthropic: ['anthropic.api_key', 'model.model'],
  bedrock: ['bedrock.region', 'bedrock.access_key_id', 'bedrock.secret_access_key', 'bedrock.session_token', 'model.model'],
  bifrost: ['bifrost.url', 'bifrost.api_key', 'model.model'],
}

const FIELD_LABELS: Record<string, string> = {
  'ollama.base_url': 'Base URL',
  'model.model': 'Model',
  'anthropic.api_key': 'API key',
  'bedrock.region': 'Region',
  'bedrock.access_key_id': 'Access key ID',
  'bedrock.secret_access_key': 'Secret access key',
  'bedrock.session_token': 'Session token',
  'bifrost.url': 'URL',
  'bifrost.api_key': 'API key',
}

// Placeholders only; the backend applies these defaults when the field is blank
const DEFAULT_MODELS: Record<Backend, string> = {
  ollama: 'qwen2.5-coder:7b',
  anthropic: 'claude-opus-5-5',
  bedrock: 'anthropic.claude-sonnet-4-5-20250929-v1:0',
  bifrost: 'claude-opus-5-5',
}

const INPUT_CLASS =
  'w-full bg-surface-container-lowest border border-outline-variant/30 rounded-lg px-3 py-2 text-xs font-mono text-on-surface placeholder:text-outline/50 focus:outline-none focus:border-primary/50 disabled:opacity-50'
const BUTTON_CLASS =
  'px-3 py-2 rounded-lg font-mono text-[11px] uppercase transition-colors disabled:opacity-40'

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

function SourceTag({ field }: { field: SettingField }) {
  const color =
    field.source === 'env' ? 'bg-secondary/15 text-secondary' :
    field.source === 'config' ? 'bg-primary/15 text-primary' :
    'bg-surface-container-highest text-outline'
  return <span className={`rounded px-1.5 py-0.5 text-[9px] uppercase font-mono ${color}`}>{field.source}</span>
}

function FieldRow({ label, field, children }: { label: string; field?: SettingField; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-4 py-2.5 border-b border-outline-variant/15 last:border-0">
      <span className="font-mono text-[11px] uppercase text-outline w-44 shrink-0 pt-2">{label}</span>
      <div className="flex-1 min-w-0 space-y-1">
        {children}
        {field?.source === 'env' && (
          <p className="text-[10px] font-mono text-secondary">Set by {field.env_var}; change it there.</p>
        )}
      </div>
      {field && <div className="pt-2"><SourceTag field={field} /></div>}
    </div>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed'
}

function ModelBackendSection({ settings }: { settings: SettingsResponse }) {
  const qc = useQueryClient()
  const fields = settings.fields
  const [backend, setBackend] = useState<Backend>('anthropic')
  const [values, setValues] = useState<Record<string, string>>({})
  const [replacing, setReplacing] = useState<Record<string, string>>({})
  const [result, setResult] = useState<ConnectionResult | null>(null)

  useEffect(() => {
    const next: Record<string, string> = {}
    for (const [key, field] of Object.entries(fields)) {
      if (!field.secret && typeof field.value === 'string') next[key] = field.value
    }
    setValues(next)
    setBackend((fields['model.backend']?.value as Backend) ?? 'anthropic')
    setReplacing({})
  }, [fields])

  const baseUrl = values['ollama.base_url']
  const { data: ollama } = useQuery({
    queryKey: ['ollama-models', baseUrl],
    queryFn: () => api.settings.ollamaModels(baseUrl),
    enabled: backend === 'ollama',
  })

  const locked = (key: string) => fields[key]?.source === 'env'

  function formValues(): Record<string, unknown> {
    const out: Record<string, unknown> = {}
    if (!locked('model.backend')) out['model.backend'] = backend
    for (const key of BACKEND_FIELDS[backend]) {
      if (locked(key)) continue
      // Blank secrets keep the saved key; blank fields fall back to the default
      out[key] = fields[key]?.secret ? (replacing[key] ?? '') : (values[key] ?? '')
    }
    return out
  }

  const save = useMutation({
    mutationFn: () => api.settings.update(formValues()),
    onSuccess: (data) => {
      qc.setQueryData(['settings'], data)
      void qc.invalidateQueries({ queryKey: ['health'] })
      setResult(null)
    },
  })
  const test = useMutation({
    mutationFn: () => api.settings.test(formValues()),
    onSuccess: setResult,
  })

  function changeBackend(next: Backend) {
    setBackend(next)
    setResult(null)
    // A model ID from one backend is meaningless on another
    if (!locked('model.model')) setValues((v) => ({ ...v, 'model.model': '' }))
  }

  const models = ollama?.models ?? null
  const currentModel = values['model.model'] ?? ''

  return (
    <Section title="Model Backend">
      <FieldRow label="Backend" field={fields['model.backend']}>
        <select
          value={backend}
          disabled={locked('model.backend')}
          onChange={(e) => changeBackend(e.target.value as Backend)}
          className={INPUT_CLASS}
        >
          {BACKENDS.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </select>
      </FieldRow>

      {BACKEND_FIELDS[backend].map((key) => {
        const field = fields[key]
        const label = FIELD_LABELS[key] ?? key
        if (field?.secret) {
          const isReplacing = key in replacing
          return (
            <FieldRow key={key} label={label} field={field}>
              {isReplacing ? (
                <input
                  type="password"
                  autoComplete="off"
                  value={replacing[key]}
                  onChange={(e) => setReplacing((r) => ({ ...r, [key]: e.target.value }))}
                  placeholder="Paste the new value"
                  className={INPUT_CLASS}
                />
              ) : (
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-on-surface">{(field.value as string | null) ?? 'not set'}</span>
                  {!locked(key) && (
                    <button
                      type="button"
                      onClick={() => setReplacing((r) => ({ ...r, [key]: '' }))}
                      className={`${BUTTON_CLASS} py-1 border border-outline-variant/30 text-on-surface-variant hover:border-primary/40`}
                    >
                      {field.value ? 'Replace' : 'Add'}
                    </button>
                  )}
                </div>
              )}
            </FieldRow>
          )
        }
        if (key === 'model.model' && backend === 'ollama' && models && models.length > 0) {
          const options = currentModel && !models.includes(currentModel) ? [currentModel, ...models] : models
          return (
            <FieldRow key={key} label={label} field={field}>
              <select
                value={currentModel || DEFAULT_MODELS.ollama}
                disabled={locked(key)}
                onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
                className={INPUT_CLASS}
              >
                {!options.includes(DEFAULT_MODELS.ollama) && !currentModel && (
                  <option value={DEFAULT_MODELS.ollama}>{DEFAULT_MODELS.ollama} (not pulled)</option>
                )}
                {options.map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </FieldRow>
          )
        }
        return (
          <FieldRow key={key} label={label} field={field}>
            <input
              type="text"
              value={values[key] ?? ''}
              disabled={locked(key)}
              onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
              placeholder={key === 'model.model' ? `default: ${DEFAULT_MODELS[backend]}` : ''}
              className={INPUT_CLASS}
            />
            {key === 'model.model' && backend === 'ollama' && models === null && (
              <p className="text-[10px] font-mono text-outline">Ollama isn't reachable at this URL, so its models can't be listed.</p>
            )}
          </FieldRow>
        )
      })}

      <div className="flex flex-wrap items-center gap-3 py-3">
        <button
          type="button"
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className={`${BUTTON_CLASS} bg-primary/10 hover:bg-primary/20 text-primary`}
        >
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={() => test.mutate()}
          disabled={test.isPending}
          className={`${BUTTON_CLASS} bg-secondary/10 hover:bg-secondary/20 text-secondary`}
        >
          {test.isPending ? 'Testing…' : 'Test connection'}
        </button>
        {save.isSuccess && !save.isPending && <span className="text-[11px] font-mono text-tertiary">Saved</span>}
        {save.isError && <span className="text-[11px] font-mono text-error">{errorMessage(save.error)}</span>}
        {test.isError && <span className="text-[11px] font-mono text-error">{errorMessage(test.error)}</span>}
        {result && (
          <span className={`text-[11px] font-mono break-all ${result.ok ? 'text-tertiary' : 'text-error'}`}>
            {result.ok ? '✓ ' : '✗ '}{result.message}
          </span>
        )}
      </div>
    </Section>
  )
}

function CodeFoldersSection({ settings }: { settings: SettingsResponse }) {
  const qc = useQueryClient()
  const field = settings.fields['workspace.roots']
  const cloneDir = settings.fields['workspace.clone_dir']?.value as string | null
  const [folders, setFolders] = useState<string[]>([])

  useEffect(() => {
    setFolders(Array.isArray(field?.value) && field.value.length > 0 ? field.value : [''])
  }, [field])

  const locked = field?.source === 'env'
  const save = useMutation({
    mutationFn: () => api.settings.update({ 'workspace.roots': folders.map((f) => f.trim()).filter(Boolean) }),
    onSuccess: (data) => {
      qc.setQueryData(['settings'], data)
      // Drop (not just invalidate) so Explorer never browses a root that is no longer allowed
      qc.removeQueries({ queryKey: ['workspace-roots'] })
      qc.removeQueries({ queryKey: ['workspace-tree'] })
    },
  })

  return (
    <Section title="Code Folders">
      <FieldRow label="Readable folders" field={field}>
        {folders.map((folder, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              type="text"
              value={folder}
              disabled={locked}
              onChange={(e) => setFolders((list) => list.map((f, i) => (i === index ? e.target.value : f)))}
              placeholder="~/code"
              className={INPUT_CLASS}
            />
            {!locked && folders.length > 1 && (
              <button
                type="button"
                onClick={() => setFolders((list) => list.filter((_, i) => i !== index))}
                className="text-outline hover:text-error"
                title="Remove folder"
              >
                <span className="material-symbols-outlined text-[16px]">close</span>
              </button>
            )}
          </div>
        ))}
        <p className="text-[10px] font-mono text-outline">
          Copilot and Explorer can only read these folders. With none set, the folder `serve` was started from is used.
        </p>
      </FieldRow>
      <Row label="Clone folder" value={cloneDir ?? '—'} />
      {!locked && (
        <div className="flex flex-wrap items-center gap-3 py-3">
          <button
            type="button"
            onClick={() => setFolders((list) => [...list, ''])}
            className={`${BUTTON_CLASS} border border-outline-variant/30 text-on-surface-variant hover:border-primary/40`}
          >
            Add folder
          </button>
          <button
            type="button"
            onClick={() => save.mutate()}
            disabled={save.isPending}
            className={`${BUTTON_CLASS} bg-primary/10 hover:bg-primary/20 text-primary`}
          >
            {save.isPending ? 'Saving…' : 'Save folders'}
          </button>
          {save.isSuccess && !save.isPending && <span className="text-[11px] font-mono text-tertiary">Saved</span>}
          {save.isError && <span className="text-[11px] font-mono text-error">{errorMessage(save.error)}</span>}
        </div>
      )}
    </Section>
  )
}

export function SettingsPanel() {
  const { data: settings, error: settingsError } = useQuery({
    queryKey: ['settings'],
    queryFn: api.settings.get,
  })
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
  })
  const { data: stats } = useQuery({
    queryKey: ['vault-stats'],
    queryFn: api.stats,
  })
  const { data: cloned } = useQuery({
    queryKey: ['cloned-repos'],
    queryFn: api.workspace.cloned,
  })

  return (
    <div className="flex-1 glass-panel p-6 flex flex-col gap-6 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="material-symbols-outlined text-primary text-[28px]">settings</span>
        <h2 className="font-sans text-headline-md font-semibold text-on-surface">Settings</h2>
        {settings && (
          <span className="text-[11px] font-mono text-outline ml-2 truncate">Saved to {settings.config_path}</span>
        )}
      </div>

      {settings?.config_error && (
        <div className="rounded border border-error/40 bg-error/10 px-3 py-2 text-xs text-error">
          The config file has an error, so saved settings are ignored and saving is disabled until it's fixed:{' '}
          {settings.config_error}
        </div>
      )}
      {settingsError && (
        <div className="rounded border border-error/40 bg-error/10 px-3 py-2 text-xs text-error">
          {errorMessage(settingsError)}
        </div>
      )}

      {settings && <ModelBackendSection settings={settings} />}
      {settings && <CodeFoldersSection settings={settings} />}

      {/* Database */}
      <Section title="Database">
        <Row label="DB Path" value={health?.db_path ?? '—'} />
        <Row label="Patterns" value={stats ? String(stats.patterns) : '—'} />
        <Row label="Chunks" value={stats ? String(stats.chunks) : '—'} />
        <Row label="Insights" value={stats ? String(stats.insights) : '—'} />
        <Row label="Languages" value={stats?.languages?.join(', ') || '—'} />
        <Row label="Categories" value={stats?.categories?.join(', ') || '—'} />
      </Section>

      {/* Clone cache */}
      <Section title="Cloned Repos">
        <Row label="Repos registered" value={cloned ? String(cloned.length) : '—'} />
        {cloned && cloned.length > 0 && (
          <div className="py-2.5">
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
      <Section title="Environment Variables (override the config file)">
        <Row label="PATTERN_VAULT_CONFIG" value="~/.pattern-vault/config.toml (default)" />
        <Row label="PATTERN_VAULT_BACKEND" value="anthropic | bedrock | bifrost | ollama" />
        <Row label="PATTERN_VAULT_DB" value="~/.pattern-vault/patterns.db (default)" />
        <Row label="PATTERN_VAULT_WORKSPACE_ROOTS" value="os.pathsep-separated code folders" />
        <Row label="PATTERN_VAULT_MODEL" value="Override model ID per backend" />
        <Row label="ANTHROPIC_API_KEY" value="Key for backend=anthropic" />
        <Row label="AWS_ACCESS_KEY_ID / SECRET" value="Optional for backend=bedrock (AWS credential chain otherwise)" />
        <Row label="BIFROST_URL" value="Required if backend=bifrost (e.g. http://localhost:8080/anthropic)" />
        <Row label="OLLAMA_BASE_URL" value="http://localhost:11434/v1 (default)" />
      </Section>
    </div>
  )
}
