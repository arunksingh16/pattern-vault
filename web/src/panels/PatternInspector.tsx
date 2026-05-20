import { useState, useEffect } from 'react'
import { GlassPanel } from '@/components/GlassPanel'
import { CodeBlock } from '@/components/CodeBlock'
import { Chip } from '@/components/Chip'
import { usePattern, useDeletePattern, useUpdatePattern } from '@/api/hooks/usePatterns'
import { useUIStore } from '@/stores/uiStore'

export function PatternInspector() {
  const selectedId = useUIStore((s) => s.selectedPatternId)
  const selectPattern = useUIStore((s) => s.selectPattern)
  const setCopilotHandoff = useUIStore((s) => s.setCopilotHandoff)
  const setActiveView = useUIStore((s) => s.setActiveView)
  const { data: pattern, isLoading } = usePattern(selectedId)
  const deleteMutation = useDeletePattern()
  const updateMutation = useUpdatePattern()

  const [notes, setNotes] = useState<string | null>(null)
  const [notesEditing, setNotesEditing] = useState(false)

  // Reset local notes draft when switching to a different pattern
  useEffect(() => {
    setNotes(null)
    setNotesEditing(false)
  }, [selectedId])

  if (!selectedId) {
    return (
      <GlassPanel className="flex-1 flex flex-col">
        <div className="h-10 px-4 flex items-center border-b border-outline-variant/20">
          <span className="font-mono text-label-caps text-on-surface-variant uppercase tracking-tighter">
            Inspector
          </span>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <div className="text-center space-y-2">
            <span className="material-symbols-outlined text-[36px] text-outline/40">code</span>
            <p className="text-on-surface-variant text-sm">Select a pattern to inspect</p>
          </div>
        </div>
      </GlassPanel>
    )
  }

  if (isLoading) {
    return (
      <GlassPanel className="flex-1 flex flex-col">
        <div className="h-10 px-4 flex items-center border-b border-outline-variant/20">
          <span className="font-mono text-label-caps text-on-surface-variant uppercase">Inspector</span>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <span className="material-symbols-outlined text-primary animate-spin">progress_activity</span>
        </div>
      </GlassPanel>
    )
  }

  if (!pattern) {
    return (
      <GlassPanel className="flex-1 flex flex-col">
        <div className="h-10 px-4 flex items-center border-b border-outline-variant/20">
          <span className="font-mono text-label-caps text-on-surface-variant uppercase">Inspector</span>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-on-surface-variant text-sm">Pattern not found</p>
        </div>
      </GlassPanel>
    )
  }

  const source = pattern.source_file || pattern.source_repo || 'manual'
  const location = pattern.line_start && pattern.line_end
    ? `${source}:${pattern.line_start}-${pattern.line_end}`
    : source

  // Sync local notes state when a different pattern is loaded
  const displayNotes = notes !== null ? notes : (pattern.user_notes ?? '')

  function handleNotesSave() {
    updateMutation.mutate(
      { id: pattern!.id, data: { user_notes: displayNotes } },
      { onSuccess: () => setNotesEditing(false) }
    )
  }

  function handleNotesCancel() {
    setNotes(null)
    setNotesEditing(false)
  }

  return (
    <GlassPanel className="flex-1 flex flex-col">
      <div className="h-10 px-4 flex items-center justify-between border-b border-outline-variant/20">
        <span className="font-mono text-label-caps text-on-surface-variant uppercase tracking-tighter">
          Inspector
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              setCopilotHandoff({ kind: 'pattern', sourceView: 'patterns', patternId: pattern.id })
              setActiveView('copilot')
            }}
            className="flex items-center gap-1 px-2 py-1 text-primary hover:bg-primary/10 rounded transition-colors font-mono text-[10px] uppercase"
            title="Discuss this pattern with Copilot"
          >
            <span className="material-symbols-outlined text-[14px]">psychology</span>
            Discuss
          </button>
          <button
            onClick={() => selectPattern(null)}
            className="text-outline hover:text-on-surface transition-colors"
          >
            <span className="material-symbols-outlined text-[16px]">close</span>
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Header */}
        <div className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-sans text-headline-md text-on-surface leading-tight">
              {pattern.name}
            </h3>
            <span className="text-[10px] text-outline shrink-0">#{pattern.id}</span>
          </div>
          <p className="text-body-base text-on-surface-variant">{pattern.summary}</p>
        </div>

        {/* Metadata */}
        <div className="bg-surface-container-lowest/50 rounded-lg border border-outline-variant/20 p-3 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Chip label={pattern.category} variant="primary" />
            <Chip label={pattern.language} variant="tertiary" />
            {pattern.tags.map((tag) => (
              <Chip key={tag} label={tag} variant="outline" />
            ))}
          </div>
          <div className="font-mono text-[11px] text-outline space-y-1">
            <p>Source: {location}</p>
            {pattern.quality_signal && <p>Quality: {pattern.quality_signal}</p>}
          </div>
        </div>

        {/* Code */}
        {pattern.chunks && pattern.chunks.length > 0 ? (
          <div className="space-y-3">
            <span className="font-mono text-label-caps text-outline uppercase">Code</span>
            {pattern.chunks.map((chunk) => (
              <CodeBlock
                key={chunk.id}
                code={chunk.code_text}
                language={pattern.language}
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-4">
            <p className="text-on-surface-variant text-sm italic">No code chunk stored</p>
          </div>
        )}

        {/* User Notes */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-mono text-label-caps text-outline uppercase">Your Notes</span>
            {!notesEditing && (
              <button
                onClick={() => { setNotes(pattern.user_notes ?? ''); setNotesEditing(true) }}
                className="flex items-center gap-1 text-outline hover:text-on-surface transition-colors font-mono text-[10px] uppercase"
              >
                <span className="material-symbols-outlined text-[13px]">edit</span>
                {displayNotes ? 'Edit' : 'Add'}
              </button>
            )}
          </div>
          {notesEditing ? (
            <div className="space-y-2">
              <textarea
                value={displayNotes}
                onChange={(e) => setNotes(e.target.value)}
                rows={4}
                placeholder="Add your perspective, usage context, caveats…"
                className="w-full bg-surface-container-lowest/60 border border-outline-variant/30 rounded-lg px-3 py-2 text-body-base text-on-surface placeholder:text-outline/50 focus:outline-none focus:border-primary/50 resize-none font-sans text-sm"
              />
              <div className="flex gap-2">
                <button
                  onClick={handleNotesSave}
                  disabled={updateMutation.isPending}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-primary/10 hover:bg-primary/20 text-primary rounded-lg transition-colors font-mono text-[11px] uppercase disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-[13px]">save</span>
                  {updateMutation.isPending ? 'Saving…' : 'Save'}
                </button>
                <button
                  onClick={handleNotesCancel}
                  className="px-3 py-1.5 text-outline hover:text-on-surface rounded-lg transition-colors font-mono text-[11px] uppercase"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <div
              className={`rounded-lg border border-outline-variant/20 px-3 py-2 min-h-[48px] cursor-pointer hover:border-outline-variant/40 transition-colors ${displayNotes ? 'text-body-base text-on-surface-variant' : 'text-outline/50 text-sm italic'}`}
              onClick={() => { setNotes(pattern.user_notes ?? ''); setNotesEditing(true) }}
            >
              {displayNotes || 'Click to add notes…'}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-2 pt-2 border-t border-outline-variant/10">
          <button
            onClick={() => {
              if (confirm(`Delete pattern #${pattern.id}?`)) {
                deleteMutation.mutate(pattern.id, {
                  onSuccess: () => selectPattern(null),
                })
              }
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-error/80 hover:text-error hover:bg-error/10 rounded-lg transition-colors font-mono text-[11px] uppercase"
          >
            <span className="material-symbols-outlined text-[14px]">delete</span>
            Delete
          </button>
        </div>
      </div>
    </GlassPanel>
  )
}
