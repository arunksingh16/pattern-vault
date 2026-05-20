import { create } from 'zustand'
import type { ChatSession } from '@/api/client'

export type View = 'explorer' | 'patterns' | 'copilot' | 'insights' | 'history' | 'usage' | 'vault' | 'mcp' | 'ingestion' | 'settings'

export type CopilotHandoff =
  | {
      kind: 'repo'
      sourceView: View
      repoOwner: string
      repoName: string
      branch: string
      localPath: string
      analyseMessage: string
      existingSession: ChatSession | null
    }
  | {
      kind: 'pattern'
      sourceView: View
      patternId: number
    }

export interface ActiveIndexJob {
  jobId: string
  title: string
  path: string
  repoName?: string | null
  sourceKind?: 'repo' | 'path'
  dryRun: boolean
  profile?: 'curated' | 'balanced' | 'comprehensive'
  includeLanguages?: string[]
  includePaths?: string[]
  excludePaths?: string[]
}

interface UIState {
  activeView: View
  sidebarExpanded: boolean
  selectedPatternId: number | null
  copilotHandoff: CopilotHandoff | null
  activeIndexJob: ActiveIndexJob | null
  setActiveView: (view: View) => void
  toggleSidebar: () => void
  selectPattern: (id: number | null) => void
  setCopilotHandoff: (data: CopilotHandoff) => void
  clearCopilotHandoff: () => void
  setActiveIndexJob: (job: ActiveIndexJob) => void
  openIndexJob: (job: ActiveIndexJob) => void
  clearActiveIndexJob: () => void
}

export const useUIStore = create<UIState>((set) => ({
  activeView: 'explorer',
  sidebarExpanded: false,
  selectedPatternId: null,
  copilotHandoff: null,
  activeIndexJob: null,
  setActiveView: (view) => set({ activeView: view }),
  toggleSidebar: () => set((s) => ({ sidebarExpanded: !s.sidebarExpanded })),
  selectPattern: (id) => set({ selectedPatternId: id }),
  setCopilotHandoff: (data) => set({ copilotHandoff: data }),
  clearCopilotHandoff: () => set({ copilotHandoff: null }),
  setActiveIndexJob: (job) => set({ activeIndexJob: job }),
  openIndexJob: (job) => set({ activeIndexJob: job, activeView: 'ingestion' }),
  clearActiveIndexJob: () => set({ activeIndexJob: null }),
}))
