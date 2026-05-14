import { useEffect, useState } from 'react'
import { createHighlighter, type Highlighter } from 'shiki'

let highlighterPromise: Promise<Highlighter> | null = null

function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ['github-dark-default'],
      langs: ['python', 'javascript', 'typescript', 'go', 'rust', 'java', 'bash', 'json', 'yaml', 'toml'],
    })
  }
  return highlighterPromise
}

interface CodeBlockProps {
  code: string
  language?: string
}

export function CodeBlock({ code, language = 'python' }: CodeBlockProps) {
  const [html, setHtml] = useState<string>('')

  useEffect(() => {
    let cancelled = false
    getHighlighter().then((hl) => {
      if (cancelled) return
      const supported = hl.getLoadedLanguages()
      const lang = supported.includes(language as never) ? language : 'text'
      const rendered = hl.codeToHtml(code, {
        lang,
        theme: 'github-dark-default',
      })
      setHtml(rendered)
    })
    return () => { cancelled = true }
  }, [code, language])

  if (!html) {
    return (
      <pre className="bg-surface-container-lowest rounded-lg p-4 overflow-x-auto border border-outline-variant/20">
        <code className="font-mono text-code-sm text-on-surface-variant whitespace-pre">{code}</code>
      </pre>
    )
  }

  return (
    <div className="relative group">
      <div
        className="[&_pre]:!bg-surface-container-lowest [&_pre]:rounded-lg [&_pre]:p-4 [&_pre]:overflow-x-auto [&_pre]:border [&_pre]:border-outline-variant/20 [&_code]:font-mono [&_code]:text-code-sm"
        dangerouslySetInnerHTML={{ __html: html }}
      />
      <button
        onClick={() => navigator.clipboard.writeText(code)}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded bg-surface-container-highest/80 hover:bg-surface-container-highest border border-outline-variant/30"
        title="Copy code"
      >
        <span className="material-symbols-outlined text-[14px] text-on-surface-variant">content_copy</span>
      </button>
    </div>
  )
}
