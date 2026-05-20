import { useQuery } from '@tanstack/react-query'
import { SideNav } from '@/components/SideNav'
import { PanelGrid } from '@/layouts/PanelGrid'
import { PatternBrowser } from '@/panels/PatternBrowser'
import { PatternInspector } from '@/panels/PatternInspector'
import { ChatPanel } from '@/panels/ChatPanel'
import { InsightsPanel } from '@/panels/InsightsPanel'
import { HistoryPanel } from '@/panels/HistoryPanel'
import { ExplorerPanel } from '@/panels/ExplorerPanel'
import { IngestionPanel } from '@/panels/IngestionPanel'
import { UsagePanel } from '@/panels/UsagePanel'
import { VaultPanel } from '@/panels/VaultPanel'
import { MCPPanel } from '@/panels/MCPPanel'
import { SettingsPanel } from '@/panels/SettingsPanel'
import { useUIStore } from '@/stores/uiStore'
import logo from '@/assets/logo.png'

function Header() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: () => fetch('/api/health').then((r) => r.json()),
  })

  return (
    <header className="fixed top-0 left-0 w-full z-50 flex justify-between items-center px-margin-desktop h-14 bg-surface-container-low/80 backdrop-blur-xl border-b border-outline-variant/30 shadow-md">
      <div className="flex items-center gap-3">
        <img src={logo} alt="Pattern Vault" className="h-8 w-auto" />
        <span className="font-sans text-headline-md font-bold text-transparent bg-clip-text bg-gradient-to-r from-primary to-secondary">
          Pattern Vault
        </span>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 px-3 py-1 bg-surface-container-highest rounded-full border border-outline-variant/30">
          <div className={`w-2 h-2 rounded-full ${health ? 'bg-tertiary' : 'bg-secondary'} animate-pulse`} />
          <span className="font-mono text-label-caps text-on-surface-variant uppercase">
            {health?.backend ?? 'connecting...'}
          </span>
        </div>
      </div>
    </header>
  )
}

function ViewRouter() {
  const { activeView } = useUIStore()

  switch (activeView) {
    case 'patterns':
      return (
        <PanelGrid
          left={<PatternBrowser />}
          right={<PatternInspector />}
        />
      )
    case 'copilot':
      return (
        <PanelGrid center={<ChatPanel />} />
      )
    case 'insights':
      return (
        <PanelGrid center={<InsightsPanel />} />
      )
    case 'history':
      return (
        <PanelGrid center={<HistoryPanel />} />
      )
    case 'usage':
      return (
        <PanelGrid center={<UsagePanel />} />
      )
    case 'explorer':
      return (
        <PanelGrid center={<ExplorerPanel />} />
      )
    case 'vault':
      return (
        <PanelGrid center={<VaultPanel />} />
      )
    case 'ingestion':
      return (
        <PanelGrid center={<IngestionPanel />} />
      )
    case 'mcp':
      return (
        <PanelGrid center={<MCPPanel />} />
      )
    case 'settings':
      return (
        <PanelGrid center={<SettingsPanel />} />
      )
    default:
      return (
        <PanelGrid
          left={<PatternBrowser />}
          right={<PatternInspector />}
        />
      )
  }
}

export default function App() {
  return (
    <div className="h-screen overflow-hidden relative flex flex-col">
      {/* Ambient underglow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-secondary/5 rounded-full blur-[120px] pointer-events-none" />
      <div className="absolute bottom-0 right-0 w-[400px] h-[400px] bg-primary/5 rounded-full blur-[100px] pointer-events-none" />

      <Header />
      <SideNav />

      <main className="ml-16 pt-14 flex-1 flex flex-col min-h-0 relative">
        <ViewRouter />
      </main>
    </div>
  )
}
