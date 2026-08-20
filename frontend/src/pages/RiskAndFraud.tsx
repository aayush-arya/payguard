import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { ShieldAlert } from 'lucide-react'
import { GlassCard, ChartCard } from '../components/ui'
import { mockRiskCases, mockRiskDistribution } from '../lib/mockData'
import { formatAmount, formatDateTime } from '../lib/format'

const LEVEL_COLOR: Record<string, string> = {
  LOW: 'var(--color-success)',
  MEDIUM: 'var(--color-warning)',
  HIGH: '#c2540a',
  BLOCKED: 'var(--color-danger)',
}

export function RiskAndFraud() {
  const distribution = mockRiskDistribution()
  const cases = mockRiskCases()

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-text">Risk & Fraud</h1>
          <p className="mt-1 text-sm text-text-muted">
            Deterministic rule-based scoring (docs/risk.md) — illustrative distribution and cases below;
            the scoring engine itself is real.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <ChartCard title="Risk distribution" subtitle="Share of assessed payments" height={220}>
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={distribution}
                dataKey="percentage"
                nameKey="level"
                innerRadius={55}
                outerRadius={80}
                paddingAngle={3}
                isAnimationActive
                animationDuration={700}
              >
                {distribution.map((d) => (
                  <Cell key={d.level} fill={LEVEL_COLOR[d.level]} stroke="none" />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface-solid)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 12,
                  fontSize: 12,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </ChartCard>

        <div className="flex flex-col justify-center gap-3 lg:col-span-1">
          {distribution.map((d) => (
            <div key={d.level} className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 text-text-muted">
                <span className="h-2 w-2 rounded-full" style={{ background: LEVEL_COLOR[d.level] }} />
                {d.level}
              </span>
              <span className="tabular-nums font-medium text-text">{d.percentage}%</span>
            </div>
          ))}
        </div>

        <GlassCard padding="lg" className="flex flex-col justify-center lg:col-span-1">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-danger-soft text-danger">
            <ShieldAlert size={18} />
          </span>
          <p className="mt-4 text-2xl font-semibold tabular-nums text-text">$38,240</p>
          <p className="mt-1 text-xs text-text-muted">Prevented fraud exposure (blocked payments, 30d)</p>
        </GlassCard>
      </div>

      <GlassCard padding="lg">
        <h2 className="mb-4 text-sm font-semibold text-text">Recent flagged payments</h2>
        <div className="flex flex-col divide-y divide-border">
          {cases.map((c) => (
            <div key={c.id} className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-text-muted">{c.paymentId.slice(0, 8)}…</span>
                <div className="flex items-center gap-3">
                  <span className="tabular-nums text-sm text-text">{formatAmount(c.amount, 'USD')}</span>
                  <span
                    className="rounded-full px-2.5 py-0.5 text-[11px] font-medium"
                    style={{ background: `${LEVEL_COLOR[c.level]}22`, color: LEVEL_COLOR[c.level] }}
                  >
                    Score {c.score}
                  </span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {c.reasons.map((r) => (
                  <span
                    key={r.label}
                    className="rounded-md border border-border bg-black/[0.02] px-2 py-1 text-[11px] text-text-muted"
                  >
                    + {r.label}
                  </span>
                ))}
              </div>
              <span className="text-[11px] text-text-faint">{formatDateTime(c.createdAt)}</span>
            </div>
          ))}
        </div>
      </GlassCard>
    </div>
  )
}
