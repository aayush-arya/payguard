import { type ReactNode } from 'react'
import { Area, AreaChart, ResponsiveContainer } from 'recharts'
import { GlassCard } from './GlassCard'
import { TrendIndicator } from './TrendIndicator'

interface MetricCardProps {
  label: string
  value: string
  icon: ReactNode
  trend?: number
  context?: string
  sparkline?: number[]
  accent?: 'primary' | 'secondary' | 'success' | 'warning' | 'danger'
}

const ACCENT_TEXT: Record<string, string> = {
  primary: 'text-primary',
  secondary: 'text-secondary',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
}
const ACCENT_BG: Record<string, string> = {
  primary: 'bg-primary-soft',
  secondary: 'bg-secondary-soft',
  success: 'bg-success-soft',
  warning: 'bg-warning-soft',
  danger: 'bg-danger-soft',
}
const ACCENT_STROKE: Record<string, string> = {
  primary: 'var(--color-primary)',
  secondary: 'var(--color-secondary)',
  success: 'var(--color-success)',
  warning: 'var(--color-warning)',
  danger: 'var(--color-danger)',
}

/** The KPI card every metric on Overview/Analytics uses -- kept small on
 * purpose (brief §8: "do not make them giant"), one number as the hero,
 * everything else a supporting label. */
export function MetricCard({
  label,
  value,
  icon,
  trend,
  context,
  sparkline,
  accent = 'primary',
}: MetricCardProps) {
  return (
    <GlassCard hoverLift padding="md" className="relative overflow-hidden">
      <div className="flex items-start justify-between">
        <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${ACCENT_BG[accent]} ${ACCENT_TEXT[accent]}`}>
          {icon}
        </span>
        {trend !== undefined && <TrendIndicator value={trend} />}
      </div>
      <p className="mt-3 text-2xl font-semibold tabular-nums tracking-tight text-text">{value}</p>
      <p className="mt-1 text-xs text-text-muted">{label}</p>
      {context && <p className="mt-2 text-[11px] text-text-faint">{context}</p>}

      {sparkline && sparkline.length > 1 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 opacity-70">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={sparkline.map((v, i) => ({ i, v }))}>
              <defs>
                <linearGradient id={`spark-${label}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ACCENT_STROKE[accent]} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={ACCENT_STROKE[accent]} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="v"
                stroke={ACCENT_STROKE[accent]}
                strokeWidth={1.5}
                fill={`url(#spark-${label})`}
                isAnimationActive
                animationDuration={600}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </GlassCard>
  )
}
