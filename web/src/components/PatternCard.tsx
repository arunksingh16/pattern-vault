import { Chip } from '@/components/Chip'
import type { Pattern } from '@/api/client'

interface PatternCardProps {
  pattern: Pattern
  selected?: boolean
  onClick: () => void
}

export function PatternCard({ pattern, selected, onClick }: PatternCardProps) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-3 rounded-lg border transition-all duration-150
        ${selected
          ? 'bg-primary-container/15 border-primary/40 glow-primary'
          : 'bg-surface-container-lowest/50 border-outline-variant/20 hover:border-outline-variant/40 hover:bg-surface-container-low/50'
        }`}
    >
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <span className="font-mono text-code-sm text-on-surface font-medium truncate">
          {pattern.name}
        </span>
        <span className="text-[10px] text-outline shrink-0">#{pattern.id}</span>
      </div>

      <p className="text-[12px] text-on-surface-variant line-clamp-2 mb-2">
        {pattern.summary}
      </p>

      <div className="flex items-center gap-1.5 flex-wrap">
        <Chip label={pattern.category} variant="primary" />
        <Chip label={pattern.language} variant="tertiary" />
        {pattern.tags.slice(0, 2).map((tag) => (
          <Chip key={tag} label={tag} variant="outline" />
        ))}
        {pattern.tags.length > 2 && (
          <span className="text-[10px] text-outline">+{pattern.tags.length - 2}</span>
        )}
      </div>
    </button>
  )
}
