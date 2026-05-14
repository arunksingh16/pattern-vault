import { useChatStore } from '@/stores/chatStore'

export function useChat() {
  const {
    messages,
    isStreaming,
    error,
    currentSessionId,
    repoContext,
    addUserMessage,
    startAssistantMessage,
    appendText,
    addToolCall,
    setToolResult,
    finishStream,
    setError,
    setSessionId,
    setRepoContext,
    clearChat,
  } = useChatStore()

  async function sendMessage(
    content: string,
    explicitRepoContext?: { owner: string; repo: string },
  ) {
    if (isStreaming || !content.trim()) return

    const activeRepoContext = explicitRepoContext ?? repoContext
    if (explicitRepoContext) {
      setRepoContext(explicitRepoContext)
    }

    addUserMessage(content)

    const apiMessages = [
      ...messages.map((m) => ({ role: m.role, content: m.content })),
      { role: 'user' as const, content },
    ]

    startAssistantMessage()

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: apiMessages,
          session_id: currentSessionId,
          ...(activeRepoContext ? { repo_context: activeRepoContext } : {}),
        }),
      })

      if (!response.ok) {
        setError(`HTTP ${response.status}: ${response.statusText}`)
        return
      }

      const sessionId = response.headers.get('X-Session-Id')
      if (sessionId && !currentSessionId) {
        setSessionId(parseInt(sessionId, 10))
      }

      const reader = response.body?.getReader()
      if (!reader) {
        setError('No response stream')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const json = line.slice(6)
          try {
            const event = JSON.parse(json)
            switch (event.type) {
              case 'text':
                appendText(event.content)
                break
              case 'tool_call':
                addToolCall(event.name, event.input)
                break
              case 'tool_result':
                setToolResult(event.name, event.result)
                break
              case 'done':
                finishStream()
                return
              case 'error':
                setError(event.message)
                return
            }
          } catch {
            // skip malformed lines
          }
        }
      }

      finishStream()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error')
    }
  }

  return { messages, isStreaming, error, sendMessage, clearChat }
}
