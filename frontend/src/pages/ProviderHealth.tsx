import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Activity } from 'lucide-react'
import { GlassCard, ChartCard } from '../components/ui'
import { mockProviderHealth } from '../lib/mockData'

export function ProviderHealth() {
  const providers = mockProviderHealth()

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">Provider Health</h1>
        <p className="mt-1 text-sm text-text-muted">
          Only MockProvider actually runs in this project (ADR-004) — the rest is illustrative of what
          multi-provider comparison would look like with real adapters.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {providers.map((p) => (
          <GlassCard key={p.name} hoverLift padding="md">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-text">{p.name}</span>
              <span
                className={`h-2 w-2 rounded-full ${p.status === 'operational' ? 'bg-success shadow-[0_0_6px_var(--color-success)]' : 'bg-warning shadow-[0_0_6px_var(--color-warning)]'}`}
              />
            </div>
            <p className="mt-3 text-xl font-semibold tabular-nums text-text">{p.availability}%</p>
            <p className="text-xs text-text-muted">Availability</p>
            <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-text-faint">
              <span>p50 {Math.round(p.latencyMs * 0.7)}ms</span>
              <span>p99 {Math.round(p.latencyMs * 2.4)}ms</span>
              <span>Success {p.successRate}%</span>
              <span>Timeout {p.timeoutRate}%</span>
            </div>
          </GlassCard>
        ))}
      </div>

      <ChartCard title="Latency comparison" subtitle="Average response time by provider" height={280}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={providers}>
            <CartesianGrid stroke="var(--color-border)" vertical={false} />
            <XAxis dataKey="name" stroke="var(--color-text-faint)" fontSize={12} tickLine={false} axisLine={false} />
            <YAxis stroke="var(--color-text-faint)" fontSize={12} tickLine={false} axisLine={false} />
            <Tooltip
              cursor={{ fill: 'rgba(255,255,255,0.03)' }}
              contentStyle={{
                background: 'var(--color-surface-solid)',
                border: '1px solid var(--color-border)',
                borderRadius: 12,
                fontSize: 12,
              }}
            />
            <Bar dataKey="latencyMs" fill="var(--color-primary)" radius={[6, 6, 0, 0]} isAnimationActive animationDuration={700} />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <GlassCard padding="lg" className="flex items-center gap-3">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-soft text-primary">
          <Activity size={16} />
        </span>
        <p className="text-xs text-text-muted">
          Real provider health for this project comes from Prometheus (<code className="rounded bg-white/5 px-1">GET /metrics</code>) —
          <code className="ml-1 rounded bg-white/5 px-1">payguard_provider_latency_seconds</code> and
          <code className="ml-1 rounded bg-white/5 px-1">payguard_provider_timeout_total</code> already exist for MockProvider.
        </p>
      </GlassCard>
    </div>
  )
}
