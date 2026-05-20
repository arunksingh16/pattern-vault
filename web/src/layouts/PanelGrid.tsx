interface PanelGridProps {
  left?: React.ReactNode
  center?: React.ReactNode
  right?: React.ReactNode
}

export function PanelGrid({ left, center, right }: PanelGridProps) {
  return (
    <div className="flex-1 min-h-0 p-gutter flex gap-panel-gap overflow-hidden">
      {left && (
        <section className="hidden lg:flex w-64 flex-col flex-shrink-0 min-h-0">
          {left}
        </section>
      )}
      <section className="flex-1 flex flex-col min-w-0 min-h-0">
        {center}
      </section>
      {right && (
        <section className="hidden xl:flex w-80 flex-col flex-shrink-0 min-h-0">
          {right}
        </section>
      )}
    </div>
  )
}
