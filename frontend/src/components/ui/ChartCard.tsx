import { type ReactNode } from 'react'
import { GlassCard } from './GlassCard'

export function ChartCard({
  title,
  subtitle,
  actions,
  children,
  height = 260,
}: {
  title: string
  subtitle?: string
  actions?: ReactNode
  children: ReactNode
  height?: number
}) {
  return (
    <GlassCard padding="lg">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-text-muted">{subtitle}</p>}
        </div>
        {actions}
      </div>
      <div style={{ height }} className="mt-4">
        {children}
      </div>
    </GlassCard>
  )
}
