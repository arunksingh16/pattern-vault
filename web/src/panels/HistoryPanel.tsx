import { useSessions, useDeleteSession } from '@/api/hooks/useHistory'
import { useChatStore, type ChatMessage } from '@/stores/chatStore'
import { useUIStore } from '@/stores/uiStore'
import { api } from '@/api/client'

export function HistoryPanel() {
  const { data: sessions, isLoading } = useSessions()
  const deleteMutation = useDeleteSession()
  const { loadSession } = useChatStore()
  const { setActiveView } = useUIStore()

  async function handleLoad(sessionId: number) {
    const data = await api.history.get(sessionId)
    const messages: ChatMessage[] = data.messages.map((m, i) => ({
      id: `hist-${sessionId}-${i}`,
      role: m.role,
      content: m.content,
      toolCalls: m.tool_calls,
    }))
    loadSession(messages, sessionId)
    setActiveView('copilot')
  }

  return (
    <div className="flex-1 glass-panel p-6 flex flex-col gap-4 overflow-hidden">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-tertiary text-[28px]">history</span>
          <h2 className="font-sans text-headline-md font-semibold text-on-surface">Chat History</h2>
        </div>
        {sessions && (
          <span className="font-mono text-label-caps text-on-surface-variant uppercase">
            {sessions.length} session{sessions.length !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div className="flex-1 overflow-y-auto space-y-2">
        {isLoading && (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-16 rounded-lg bg-surface-container-high/50 animate-pulse" />
            ))}
          </div>
        )}

        {sessions && sessions.length === 0 && (
          <div className="flex-1 flex items-center justify-center py-12">
            <p className="text-outline text-sm">No conversations yet. Start chatting in the Copilot view.</p>
          </div>
        )}

        {sessions?.map((session) => (
          <div
            key={session.id}
            className="group flex items-center gap-3 p-3 rounded-lg border border-outline-variant/20 bg-surface-container-high/40 hover:border-primary/40 transition-colors cursor-pointer"
            onClick={() => handleLoad(session.id)}
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm text-on-surface truncate font-medium">
                {session.title || 'Untitled conversation'}
              </p>
              <p className="text-xs text-on-surface-variant mt-1">
                {new Date(session.updated_at * 1000).toLocaleString()}
              </p>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation()
                deleteMutation.mutate(session.id)
              }}
              className="opacity-0 group-hover:opacity-100 transition-opacity p-1 text-on-surface-variant hover:text-error"
              title="Delete session"
            >
              <span className="material-symbols-outlined text-[18px]">delete</span>
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
