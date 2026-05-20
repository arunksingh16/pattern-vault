import { useState } from 'react'
import type { ToolCall } from '@/stores/chatStore'

interface ToolStepProps {
  toolCall: ToolCall
}

export function ToolStep({ toolCall }: ToolStepProps) {
  const [expanded, setExpanded] = useState(false)
  const isLoading = toolCall.result === undefined

  return (
    <div className="border border-outline-variant/20 rounded-lg overflow-hidden bg-surface-container-lowest/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-container-highest/30 transition-colors"
      >
        {isLoading ? (
          <span className="material-symbols-outlined text-[14px] text-primary animate-spin">progress_activity</span>
        ) : (
          <span className="material-symbols-outlined text-[14px] text-tertiary">check_circle</span>
        )}
        <span className="font-mono text-[11px] text-on-surface-variant flex-1">
          {toolCall.name}({Object.keys(toolCall.input).join(', ')})
        </span>
        <span className={`material-symbols-outlined text-[14px] text-outline transition-transform ${expanded ? 'rotate-180' : ''}`}>
          expand_more
        </span>
      </button>

      {expanded && (
        <div className="px-3 pb-2 space-y-2">
          <div className="font-mono text-[10px] text-outline">
            <pre className="whitespace-pre-wrap break-all bg-surface-container-highest/30 rounded p-2 max-h-32 overflow-y-auto">
              {JSON.stringify(toolCall.input, null, 2)}
            </pre>
          </div>
          {toolCall.result && (
            <div className="font-mono text-[10px] text-on-surface-variant">
              <pre className="whitespace-pre-wrap break-all bg-surface-container-highest/30 rounded p-2 max-h-48 overflow-y-auto">
                {toolCall.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
