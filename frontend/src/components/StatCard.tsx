import type { LucideIcon } from 'lucide-react'
import './stat-card.css'

interface StatCardProps {
  title: string
  value: string
  hint?: string
  accent?: string
  icon: LucideIcon
}

export function StatCard({ title, value, hint, accent = 'var(--accent)', icon: Icon }: StatCardProps) {
  return (
    <section className="stat-card">
      <div className="stat-card__header">
        <span className="stat-card__title">{title}</span>
        <span className="stat-card__icon" style={{ color: accent }}>
          <Icon size={18} />
        </span>
      </div>
      <div className="stat-card__value">{value}</div>
      {hint ? <div className="stat-card__hint">{hint}</div> : null}
    </section>
  )
}
