import { create } from 'zustand'

export interface ToolCall {
  name: string
  input: Record<string, unknown>
  result?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCall[]
}

interface ChatState {
  messages: ChatMessage[]
  isStreaming: boolean
  error: string | null
  currentSessionId: number | null
  repoContext: { owner: string; repo: string } | null

  addUserMessage: (content: string) => void
  startAssistantMessage: () => void
  appendText: (text: string) => void
  addToolCall: (name: string, input: Record<string, unknown>) => void
  setToolResult: (name: string, result: string) => void
  finishStream: () => void
  setError: (message: string) => void
  clearChat: () => void
  setSessionId: (id: number | null) => void
  setRepoContext: (ctx: { owner: string; repo: string } | null) => void
  loadSession: (messages: ChatMessage[], sessionId: number) => void
}

let msgCounter = 0
function nextId(): string {
  return `msg-${++msgCounter}-${Date.now()}`
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isStreaming: false,
  error: null,
  currentSessionId: null,
  repoContext: null,

  addUserMessage: (content) =>
    set((s) => ({
      messages: [...s.messages, { id: nextId(), role: 'user', content }],
      error: null,
    })),

  startAssistantMessage: () =>
    set((s) => ({
      messages: [...s.messages, { id: nextId(), role: 'assistant', content: '', toolCalls: [] }],
      isStreaming: true,
      error: null,
    })),

  appendText: (text) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last?.role === 'assistant') {
        msgs[msgs.length - 1] = { ...last, content: last.content + text }
      }
      return { messages: msgs }
    }),

  addToolCall: (name, input) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last?.role === 'assistant') {
        const toolCalls = [...(last.toolCalls || []), { name, input }]
        msgs[msgs.length - 1] = { ...last, toolCalls }
      }
      return { messages: msgs }
    }),

  setToolResult: (name, result) =>
    set((s) => {
      const msgs = [...s.messages]
      const last = msgs[msgs.length - 1]
      if (last?.role === 'assistant' && last.toolCalls) {
        const toolCalls = [...last.toolCalls]
        const idx = toolCalls.map((tc) => tc.name === name && !tc.result).lastIndexOf(true)
        if (idx >= 0) {
          toolCalls[idx] = { ...toolCalls[idx], result }
        }
        msgs[msgs.length - 1] = { ...last, toolCalls }
      }
      return { messages: msgs }
    }),

  finishStream: () => set({ isStreaming: false }),

  setError: (message) => set({ isStreaming: false, error: message }),

  clearChat: () => set({ messages: [], isStreaming: false, error: null, currentSessionId: null, repoContext: null }),

  setSessionId: (id) => set({ currentSessionId: id }),

  setRepoContext: (ctx) => set({ repoContext: ctx }),

  loadSession: (messages, sessionId) =>
    set({ messages, currentSessionId: sessionId, isStreaming: false, error: null }),
}))
