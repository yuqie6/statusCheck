import './status-pill.css'

interface StatusPillProps {
  label: string
  tone: 'good' | 'warn' | 'bad' | 'muted'
}

export function StatusPill({ label, tone }: StatusPillProps) {
  return <span className={`status-pill status-pill--${tone}`}>{label}</span>
}
