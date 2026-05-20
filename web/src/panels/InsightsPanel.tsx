import { useState } from 'react'
import { useInsights, useCreateInsight, useDeleteInsight } from '@/api/hooks/useInsights'

export function InsightsPanel() {
  const { data: insights, isLoading } = useInsights()
  const createMutation = useCreateInsight()
  const deleteMutation = useDeleteInsight()

  const [showForm, setShowForm] = useState(false)
  const [repoPath, setRepoPath] = useState('')
  const [insightText, setInsightText] = useState('')
  const [tagsInput, setTagsInput] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!repoPath.trim() || !insightText.trim()) return
    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    createMutation.mutate(
      { repo_path: repoPath, insight_text: insightText, tags },
      {
        onSuccess: () => {
          setRepoPath('')
          setInsightText('')
          setTagsInput('')
          setShowForm(false)
        },
      },
    )
  }

  return (
    <div className="flex-1 glass-panel p-6 flex flex-col gap-4 overflow-hidden">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-secondary text-[28px]">insights</span>
          <h2 className="font-sans text-headline-md font-semibold text-on-surface">Insights</h2>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-md bg-primary/20 text-primary border border-primary/30 hover:bg-primary/30 transition-colors"
        >
          <span className="material-symbols-outlined text-[16px]">{showForm ? 'close' : 'add'}</span>
          {showForm ? 'Cancel' : 'Add Insight'}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="flex flex-col gap-3 p-4 rounded-lg border border-outline-variant/30 bg-surface-container/60">
          <input
            type="text"
            placeholder="Repository path (e.g. /path/to/repo)"
            value={repoPath}
            onChange={(e) => setRepoPath(e.target.value)}
            className="px-3 py-2 text-sm rounded bg-surface-container-lowest border border-outline-variant/30 text-on-surface placeholder:text-outline focus:border-primary/50 focus:outline-none"
          />
          <textarea
            placeholder="Insight observation..."
            value={insightText}
            onChange={(e) => setInsightText(e.target.value)}
            rows={3}
            className="px-3 py-2 text-sm rounded bg-surface-container-lowest border border-outline-variant/30 text-on-surface placeholder:text-outline focus:border-primary/50 focus:outline-none resize-none"
          />
          <input
            type="text"
            placeholder="Tags (comma-separated)"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            className="px-3 py-2 text-sm rounded bg-surface-container-lowest border border-outline-variant/30 text-on-surface placeholder:text-outline focus:border-primary/50 focus:outline-none"
          />
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="self-end px-4 py-2 text-xs font-medium rounded bg-gradient-to-r from-primary to-secondary text-on-primary hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {createMutation.isPending ? 'Saving...' : 'Save Insight'}
          </button>
        </form>
      )}

      <div className="flex-1 overflow-y-auto space-y-3">
        {isLoading && (
          <div className="space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 rounded-lg bg-surface-container-high/50 animate-pulse" />
            ))}
          </div>
        )}

        {insights && insights.length === 0 && (
          <div className="flex items-center justify-center py-12">
            <p className="text-outline text-sm">No insights yet. Add one manually or let the agent discover them.</p>
          </div>
        )}

        {insights?.map((insight) => (
          <div
            key={insight.id}
            className="group p-4 rounded-lg border border-outline-variant/20 bg-surface-container-high/40"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm text-on-surface leading-relaxed">{insight.insight_text}</p>
              <button
                onClick={() => deleteMutation.mutate(insight.id)}
                className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-on-surface-variant hover:text-error flex-shrink-0"
                title="Delete insight"
              >
                <span className="material-symbols-outlined text-[16px]">delete</span>
              </button>
            </div>
            <div className="flex items-center gap-3 mt-2">
              <span className="font-mono text-[10px] text-on-surface-variant bg-surface-container-lowest px-2 py-0.5 rounded">
                {insight.repo_path}
              </span>
              {insight.tags.map((tag) => (
                <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">
                  {tag}
                </span>
              ))}
              <span className="ml-auto text-[10px] text-outline">
                {new Date(insight.created_at * 1000).toLocaleDateString()}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
