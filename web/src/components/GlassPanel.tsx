interface GlassPanelProps {
  children: React.ReactNode
  className?: string
  elevated?: boolean
}

export function GlassPanel({ children, className = '', elevated }: GlassPanelProps) {
  return (
    <div className={`${elevated ? 'glass-panel-elevated' : 'glass-panel'} min-h-0 ${className}`}>
      {children}
    </div>
  )
}
