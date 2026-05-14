import { useRef, useEffect, useState } from 'react'
import { GlassPanel } from '@/components/GlassPanel'
import { ToolStep } from '@/components/ToolStep'
import { useChat } from '@/api/hooks/useChat'
import { useUIStore } from '@/stores/uiStore'
import { usePattern } from '@/api/hooks/usePatterns'
import type { ChatMessage } from '@/stores/chatStore'

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[85%] space-y-2 ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-primary/20 text-on-surface rounded-br-md'
              : 'bg-surface-container-highest/50 text-on-surface rounded-bl-md'
          }`}
        >
          {message.content || (
            <span className="text-on-surface-variant/50 italic">Thinking...</span>
          )}
        </div>

        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="space-y-1.5 w-full">
            {message.toolCalls.map((tc, i) => (
              <ToolStep key={`${tc.name}-${i}`} toolCall={tc} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function ChatPanel() {
  const { messages, isStreaming, error, sendMessage, clearChat } = useChat()
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  const discussPatternId = useUIStore((s) => s.discussPatternId)
  const clearDiscussPattern = useUIStore((s) => s.clearDiscussPattern)
  const { data: discussPattern } = usePattern(discussPatternId)

  const pendingAnalyseData = useUIStore((s) => s.pendingAnalyseData)
  const clearPendingAnalyse = useUIStore((s) => s.clearPendingAnalyse)

  // Auto-submit when navigated here via "Discuss" from Inspector
  useEffect(() => {
    if (discussPatternId && discussPattern && !isStreaming) {
      const codeSnippet = discussPattern.chunks?.[0]?.code_text ?? ''
      const msg = `Let's discuss this pattern:\n\n**${discussPattern.name}**\n\n${discussPattern.summary}${codeSnippet ? `\n\n\`\`\`${discussPattern.language}\n${codeSnippet}\n\`\`\`` : ''}`
      clearDiscussPattern()
      sendMessage(msg)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [discussPatternId, discussPattern])

  // Auto-submit when navigated here via "Analyse" from Explorer
  useEffect(() => {
    if (pendingAnalyseData && !isStreaming) {
      const { message, repoOwner, repoName } = pendingAnalyseData
      clearPendingAnalyse()
      sendMessage(message, { owner: repoOwner, repo: repoName })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingAnalyseData])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!input.trim() || isStreaming) return
    sendMessage(input.trim())
    setInput('')
  }

  return (
    <GlassPanel className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="h-12 px-6 flex items-center justify-between border-b border-outline-variant/20 bg-surface-container-highest/30 shrink-0">
        <div className="flex items-center gap-3">
          <span
            className="material-symbols-outlined text-primary text-[20px]"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            auto_awesome
          </span>
          <span className="font-mono text-label-caps text-on-surface uppercase">
            Knowledge Copilot
          </span>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="text-outline hover:text-on-surface transition-colors"
            title="Clear chat"
          >
            <span className="material-symbols-outlined text-[18px]">delete_sweep</span>
          </button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="flex-1 flex items-center justify-center h-full">
            <div className="text-center space-y-4 max-w-sm">
              <span className="material-symbols-outlined text-[48px] text-primary/50">chat</span>
              <p className="text-on-surface-variant">
                Ask about your indexed patterns, or point me at a repository to scan.
              </p>
              <div className="flex flex-wrap gap-2 justify-center">
                {['Search for retry patterns', 'Scan /path/to/repo', 'What patterns do I have?'].map(
                  (suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => {
                        setInput(suggestion)
                      }}
                      className="px-3 py-1.5 text-[11px] font-mono text-primary/80 border border-primary/30 rounded-full hover:bg-primary/10 transition-colors"
                    >
                      {suggestion}
                    </button>
                  )
                )}
              </div>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {isStreaming && (
          <div className="flex items-center gap-2 text-on-surface-variant">
            <span className="material-symbols-outlined text-[16px] text-primary animate-spin">
              progress_activity
            </span>
            <span className="text-[11px] font-mono uppercase">Processing...</span>
          </div>
        )}

        {error && (
          <div className="px-4 py-2.5 rounded-lg bg-error/10 border border-error/30 text-error text-sm">
            {error}
          </div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-4 border-t border-outline-variant/20 shrink-0">
        <div className="flex items-center gap-3 bg-surface-container-lowest border border-outline-variant/30 rounded-xl px-4 py-3 focus-within:border-primary/50 transition-colors">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about patterns, scan a repo..."
            className="flex-1 bg-transparent text-on-surface font-mono text-code-sm outline-none placeholder:text-on-surface-variant/50"
            disabled={isStreaming}
          />
          <button
            type="submit"
            disabled={isStreaming || !input.trim()}
            className="text-primary disabled:text-outline/50 hover:text-primary/80 transition-colors"
          >
            <span className="material-symbols-outlined text-[20px]">send</span>
          </button>
        </div>
      </form>
    </GlassPanel>
  )
}
