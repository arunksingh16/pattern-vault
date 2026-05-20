import { useRef, useEffect, useState } from 'react'
import { GlassPanel } from '@/components/GlassPanel'
import { ToolStep } from '@/components/ToolStep'
import { useChat } from '@/api/hooks/useChat'
import { useUIStore } from '@/stores/uiStore'
import { usePattern } from '@/api/hooks/usePatterns'
import { api, type Pattern } from '@/api/client'
import { useChatStore, type ChatMessage } from '@/stores/chatStore'

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

function buildPatternContextMessage(pattern: Pattern, question?: string) {
  const codeSnippet = pattern.chunks?.[0]?.code_text ?? ''
  const patternContext = `Pattern context:\n\n**${pattern.name}**\n\n${pattern.summary}${codeSnippet ? `\n\n\`\`\`${pattern.language}\n${codeSnippet}\n\`\`\`` : ''}`
  if (!question) {
    return `Let's discuss this pattern:\n\n${patternContext}`
  }
  return `${question}\n\n---\n\n${patternContext}`
}

export function ChatPanel() {
  const { messages, isStreaming, error, sendMessage, clearChat } = useChat()
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const setActiveView = useUIStore((s) => s.setActiveView)
  const copilotHandoff = useUIStore((s) => s.copilotHandoff)
  const clearCopilotHandoff = useUIStore((s) => s.clearCopilotHandoff)
  const patternHandoffId = copilotHandoff?.kind === 'pattern' ? copilotHandoff.patternId : null
  const { data: handoffPattern } = usePattern(patternHandoffId)
  const loadSession = useChatStore((s) => s.loadSession)
  const repoContext = useChatStore((s) => s.repoContext)
  const setRepoContext = useChatStore((s) => s.setRepoContext)
  const setChatError = useChatStore((s) => s.setError)

  // Clear stale repo scope when landing on Copilot with no active conversation and no handoff pending
  useEffect(() => {
    if (!copilotHandoff && messages.length === 0 && repoContext) {
      setRepoContext(null)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  function focusComposer() {
    requestAnimationFrame(() => {
      inputRef.current?.focus()
    })
  }

  function handleCancelHandoff() {
    if (!copilotHandoff) return
    const previousView = copilotHandoff.sourceView
    clearCopilotHandoff()
    setActiveView(previousView)
  }

  async function handleContinueSession() {
    if (!copilotHandoff || copilotHandoff.kind !== 'repo' || !copilotHandoff.existingSession) return

    try {
      const result = await api.history.get(copilotHandoff.existingSession.id)
      const sessionMessages = result.messages.map((message) => ({
        id: `hist-${message.id}`,
        role: message.role,
        content: message.content,
        toolCalls: message.tool_calls,
      }))
      loadSession(sessionMessages, result.session_id)
      setRepoContext({ owner: copilotHandoff.repoOwner, repo: copilotHandoff.repoName })
      clearCopilotHandoff()
    } catch (e) {
      setChatError(e instanceof Error ? e.message : 'Failed to load conversation')
    }
  }

  function handleStartFresh() {
    clearChat()
    if (copilotHandoff?.kind === 'repo') {
      setRepoContext({ owner: copilotHandoff.repoOwner, repo: copilotHandoff.repoName })
    }
    focusComposer()
  }

  function handleAskQuestion() {
    if (copilotHandoff?.kind === 'repo') {
      setRepoContext({ owner: copilotHandoff.repoOwner, repo: copilotHandoff.repoName })
    }
    focusComposer()
  }

  async function handleRunHandoffAction() {
    if (!copilotHandoff || isStreaming) return

    clearChat()

    if (copilotHandoff.kind === 'repo') {
      clearCopilotHandoff()
      await sendMessage(copilotHandoff.analyseMessage, {
        owner: copilotHandoff.repoOwner,
        repo: copilotHandoff.repoName,
      })
      return
    }

    if (!handoffPattern) {
      setChatError('Pattern details are still loading')
      return
    }

    clearCopilotHandoff()
    await sendMessage(buildPatternContextMessage(handoffPattern))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!input.trim() || isStreaming) return

    const nextInput = input.trim()
    setInput('')

    if (copilotHandoff?.kind === 'repo') {
      clearChat()
      clearCopilotHandoff()
      await sendMessage(nextInput, {
        owner: copilotHandoff.repoOwner,
        repo: copilotHandoff.repoName,
      })
      return
    }

    if (copilotHandoff?.kind === 'pattern') {
      if (!handoffPattern) {
        setChatError('Pattern details are still loading')
        setInput(nextInput)
        return
      }
      clearChat()
      clearCopilotHandoff()
      await sendMessage(buildPatternContextMessage(handoffPattern, nextInput))
      return
    }

    await sendMessage(nextInput)
  }

  return (
    <GlassPanel className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="min-h-12 px-6 py-3 flex items-start justify-between gap-4 border-b border-outline-variant/20 bg-surface-container-highest/30 shrink-0">
        <div className="flex items-start gap-3 min-w-0">
          <span
            className="material-symbols-outlined text-primary text-[20px] mt-0.5"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            auto_awesome
          </span>
          <div className="min-w-0 space-y-2">
            <span className="block font-mono text-label-caps text-on-surface uppercase">
              Knowledge Copilot
            </span>
            {copilotHandoff?.kind === 'repo' ? (
              <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1">
                <span className="material-symbols-outlined text-[14px] text-primary">ads_click</span>
                <span className="font-mono text-[11px] uppercase text-primary truncate">
                  Pending repo: {copilotHandoff.repoOwner}/{copilotHandoff.repoName}
                </span>
              </div>
            ) : repoContext ? (
              <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-secondary/30 bg-secondary/10 px-3 py-1">
                <span className="material-symbols-outlined text-[14px] text-secondary">target</span>
                <span className="font-mono text-[11px] uppercase text-secondary truncate">
                  Scoped to: {repoContext.owner}/{repoContext.repo}
                </span>
              </div>
            ) : copilotHandoff?.kind === 'pattern' ? (
              <div className="inline-flex max-w-full items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3 py-1">
                <span className="material-symbols-outlined text-[14px] text-primary">code_blocks</span>
                <span className="font-mono text-[11px] uppercase text-primary truncate">
                  Pending pattern discussion
                </span>
              </div>
            ) : null}
          </div>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="shrink-0 text-outline hover:text-on-surface transition-colors"
            title="Clear chat"
          >
            <span className="material-symbols-outlined text-[18px]">delete_sweep</span>
          </button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {repoContext && !copilotHandoff && (
          <div className="rounded-2xl border border-secondary/20 bg-secondary/5 p-4 flex items-start justify-between gap-3">
            <div className="space-y-1">
              <p className="font-mono text-[11px] uppercase tracking-wide text-secondary">Repo scope active</p>
              <p className="text-sm text-on-surface">
                This conversation is scoped to {repoContext.owner}/{repoContext.repo}.
              </p>
              <p className="text-[11px] text-on-surface-variant">
                Questions you send here will keep using that repo context until you clear the chat or switch scope.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setRepoContext(null)}
              className="shrink-0 px-3 py-2 rounded-lg text-outline font-mono text-[11px] uppercase hover:text-on-surface transition-colors"
            >
              Clear scope
            </button>
          </div>
        )}

        {copilotHandoff && (
          <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4 space-y-4">
            {copilotHandoff.kind === 'repo' ? (
              <>
                <div className="space-y-2">
                  <p className="font-mono text-[11px] uppercase tracking-wide text-primary">Repo handoff</p>
                  <h3 className="font-sans text-title-lg text-on-surface">
                    What do you want to do with {copilotHandoff.repoOwner}/{copilotHandoff.repoName}?
                  </h3>
                  <p className="text-sm text-on-surface-variant">
                    Nothing will run until you choose an action or type your own question.
                  </p>
                  <p className="font-mono text-[11px] text-outline">
                    {copilotHandoff.branch} · {copilotHandoff.localPath}
                  </p>
                  {copilotHandoff.existingSession && (
                    <p className="text-[11px] font-mono text-on-surface-variant">
                      Previous conversation from {new Date(copilotHandoff.existingSession.updated_at * 1000).toLocaleDateString()} is available.
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handleAskQuestion}
                    className="px-3 py-2 rounded-lg bg-surface-container-highest/70 text-on-surface font-mono text-[11px] uppercase hover:bg-surface-container-highest transition-colors"
                  >
                    Ask a question below
                  </button>
                  {copilotHandoff.existingSession && (
                    <button
                      type="button"
                      onClick={handleContinueSession}
                      className="px-3 py-2 rounded-lg bg-primary/10 text-primary font-mono text-[11px] uppercase hover:bg-primary/20 transition-colors"
                    >
                      Continue existing conversation
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={handleStartFresh}
                    className="px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant font-mono text-[11px] uppercase hover:border-primary/30 hover:text-on-surface transition-colors"
                  >
                    Start fresh conversation
                  </button>
                  <button
                    type="button"
                    onClick={handleRunHandoffAction}
                    className="px-3 py-2 rounded-lg bg-secondary/10 text-secondary font-mono text-[11px] uppercase hover:bg-secondary/20 transition-colors"
                  >
                    Scan/analyse repo now
                  </button>
                  <button
                    type="button"
                    onClick={handleCancelHandoff}
                    className="px-3 py-2 rounded-lg text-outline font-mono text-[11px] uppercase hover:text-on-surface transition-colors"
                  >
                    Cancel and go back
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <p className="font-mono text-[11px] uppercase tracking-wide text-primary">Pattern handoff</p>
                  <h3 className="font-sans text-title-lg text-on-surface">
                    What do you want to do with this pattern?
                  </h3>
                  <p className="text-sm text-on-surface-variant">
                    Nothing will run until you choose an action or type your own question.
                  </p>
                  {handoffPattern && (
                    <p className="text-sm text-on-surface">
                      {handoffPattern.name}
                    </p>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handleAskQuestion}
                    className="px-3 py-2 rounded-lg bg-surface-container-highest/70 text-on-surface font-mono text-[11px] uppercase hover:bg-surface-container-highest transition-colors"
                  >
                    Ask a question below
                  </button>
                  <button
                    type="button"
                    onClick={handleStartFresh}
                    className="px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant font-mono text-[11px] uppercase hover:border-primary/30 hover:text-on-surface transition-colors"
                  >
                    Start fresh conversation
                  </button>
                  <button
                    type="button"
                    onClick={handleRunHandoffAction}
                    className="px-3 py-2 rounded-lg bg-secondary/10 text-secondary font-mono text-[11px] uppercase hover:bg-secondary/20 transition-colors"
                  >
                    Discuss pattern now
                  </button>
                  <button
                    type="button"
                    onClick={handleCancelHandoff}
                    className="px-3 py-2 rounded-lg text-outline font-mono text-[11px] uppercase hover:text-on-surface transition-colors"
                  >
                    Cancel and go back
                  </button>
                </div>
              </>
            )}
          </div>
        )}

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
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={copilotHandoff?.kind === 'repo'
              ? `Ask about ${copilotHandoff.repoOwner}/${copilotHandoff.repoName}...`
              : repoContext
                ? `Ask about ${repoContext.owner}/${repoContext.repo}...`
              : copilotHandoff?.kind === 'pattern'
                ? 'Ask about this pattern...'
                : 'Ask about patterns, scan a repo...'}
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
