import type { PropsWithChildren, ReactNode } from 'react'
import './panel.css'

interface PanelProps extends PropsWithChildren {
  title: string
  subtitle?: string
  action?: ReactNode
}

export function Panel({ title, subtitle, action, children }: PanelProps) {
  return (
    <section className="panel">
      <header className="panel__header">
        <div>
          <h2 className="panel__title">{title}</h2>
          {subtitle ? <p className="panel__subtitle">{subtitle}</p> : null}
        </div>
        {action ? <div className="panel__action">{action}</div> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  )
}
