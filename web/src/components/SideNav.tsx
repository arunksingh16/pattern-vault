import { useUIStore } from '@/stores/uiStore'

const navItems = [
  { id: 'explorer' as const, icon: 'folder_open', label: 'Explorer' },
  { id: 'patterns' as const, icon: 'hub', label: 'Patterns' },
  { id: 'copilot' as const, icon: 'psychology', label: 'Copilot' },
  { id: 'insights' as const, icon: 'insights', label: 'Insights' },
  { id: 'history' as const, icon: 'history', label: 'History' },
  { id: 'usage' as const, icon: 'query_stats', label: 'Usage' },
  { id: 'vault' as const, icon: 'inventory_2', label: 'Vault' },
  { id: 'mcp' as const, icon: 'monitoring', label: 'MCP' },
]

export function SideNav() {
  const { activeView, setActiveView, sidebarExpanded } = useUIStore()

  return (
    <aside
      className={`fixed left-0 top-14 h-[calc(100vh-3.5rem)] z-40 flex flex-col justify-between
        bg-surface-container/90 backdrop-blur-2xl border-r border-outline-variant/20
        transition-all duration-300 ${sidebarExpanded ? 'w-52' : 'w-16'} group hover:w-52`}
    >
      <div className="flex flex-col pt-6 overflow-hidden">
        <div className="flex items-center gap-4 px-4 mb-8">
          <div className="w-8 h-8 rounded bg-gradient-to-br from-primary to-secondary flex-shrink-0" />
          <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-300 whitespace-nowrap">
            <p className="font-mono text-label-caps text-on-surface leading-none uppercase">Vault OS</p>
            <p className="text-[9px] text-outline mt-1 uppercase tracking-tighter">v0.1.0</p>
          </div>
        </div>

        <nav className="flex flex-col gap-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveView(item.id)}
              className={`flex items-center gap-4 px-4 py-3 text-left transition-all w-full
                ${activeView === item.id
                  ? 'bg-primary-container/20 text-primary border-r-2 border-secondary'
                  : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-bright/50'
                }`}
            >
              <span className="material-symbols-outlined text-[20px]">{item.icon}</span>
              <span className="font-mono text-label-caps opacity-0 group-hover:opacity-100 transition-opacity uppercase">
                {item.label}
              </span>
            </button>
          ))}
        </nav>
      </div>

      <div className="flex flex-col gap-1 pb-6">
        <button className="flex items-center gap-4 px-4 py-3 text-on-surface-variant hover:text-on-surface w-full">
          <span className="material-symbols-outlined text-[20px]">settings</span>
          <span className="font-mono text-label-caps opacity-0 group-hover:opacity-100 transition-opacity uppercase">
            Settings
          </span>
        </button>
      </div>
    </aside>
  )
}
