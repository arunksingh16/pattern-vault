import { create } from 'zustand'

type View = 'explorer' | 'patterns' | 'copilot' | 'insights' | 'history' | 'usage' | 'vault' | 'mcp' | 'ingestion'

export interface PendingAnalyseData {
  message: string
  repoOwner: string
  repoName: string
}

export interface ActiveIndexJob {
  jobId: string
  title: string
  path: string
  repoName?: string | null
  sourceKind?: 'repo' | 'path'
  dryRun: boolean
}

interface UIState {
  activeView: View
  sidebarExpanded: boolean
  selectedPatternId: number | null
  discussPatternId: number | null
  pendingAnalyseData: PendingAnalyseData | null
  activeIndexJob: ActiveIndexJob | null
  setActiveView: (view: View) => void
  toggleSidebar: () => void
  selectPattern: (id: number | null) => void
  setDiscussPattern: (id: number) => void
  clearDiscussPattern: () => void
  setPendingAnalyse: (data: PendingAnalyseData) => void
  clearPendingAnalyse: () => void
  setActiveIndexJob: (job: ActiveIndexJob) => void
  clearActiveIndexJob: () => void
}

export const useUIStore = create<UIState>((set) => ({
  activeView: 'patterns',
  sidebarExpanded: false,
  selectedPatternId: null,
  discussPatternId: null,
  pendingAnalyseData: null,
  activeIndexJob: null,
  setActiveView: (view) => set({ activeView: view }),
  toggleSidebar: () => set((s) => ({ sidebarExpanded: !s.sidebarExpanded })),
  selectPattern: (id) => set({ selectedPatternId: id }),
  setDiscussPattern: (id) => set({ discussPatternId: id }),
  clearDiscussPattern: () => set({ discussPatternId: null }),
  setPendingAnalyse: (data) => set({ pendingAnalyseData: data }),
  clearPendingAnalyse: () => set({ pendingAnalyseData: null }),
  setActiveIndexJob: (job) => set({ activeIndexJob: job }),
  clearActiveIndexJob: () => set({ activeIndexJob: null }),
}))
