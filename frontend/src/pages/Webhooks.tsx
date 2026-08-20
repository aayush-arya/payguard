import { useState, type ReactNode } from 'react'
import { CheckCircle2, RotateCw, Copy, XCircle } from 'lucide-react'
import { GlassCard, MetricCard, StatusBadge, Modal } from '../components/ui'
import { mockWebhookEvents, type WebhookEventRow } from '../lib/mockData'
import { formatDateTime } from '../lib/format'

const STATUS_ICON: Record<WebhookEventRow['status'], typeof CheckCircle2> = {
  DELIVERED: CheckCircle2,
  RETRIED: RotateCw,
  DUPLICATE: Copy,
  FAILED: XCircle,
}

export function Webhooks() {
  const events = mockWebhookEvents()
  const [selected, setSelected] = useState<WebhookEventRow | null>(null)

  const counts = events.reduce(
    (acc, e) => ({ ...acc, [e.status]: (acc[e.status] ?? 0) + 1 }),
    {} as Record<string, number>,
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-text">Webhook Monitor</h1>
        <p className="mt-1 text-sm text-text-muted">
          HMAC-verified provider deliveries (docs/webhooks.md) — illustrative event history below; signature
          verification and dedup are real (packages/webhooks).
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard label="Delivered" value={String(counts.DELIVERED ?? 0)} icon={<CheckCircle2 size={16} />} accent="success" />
        <MetricCard label="Failed" value={String(counts.FAILED ?? 0)} icon={<XCircle size={16} />} accent="danger" />
        <MetricCard label="Retried" value={String(counts.RETRIED ?? 0)} icon={<RotateCw size={16} />} accent="warning" />
        <MetricCard label="Duplicate" value={String(counts.DUPLICATE ?? 0)} icon={<Copy size={16} />} accent="secondary" />
      </div>

      <GlassCard padding="none">
        <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-text-faint">
              <th className="px-5 py-3 font-medium">Event</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Attempts</th>
              <th className="px-5 py-3 font-medium">Latency</th>
              <th className="px-5 py-3 font-medium">Signature</th>
              <th className="px-5 py-3 font-medium">Received</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => {
              const Icon = STATUS_ICON[e.status]
              return (
                <tr
                  key={e.id}
                  onClick={() => setSelected(e)}
                  className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-black/[0.02]"
                >
                  <td className="px-5 py-3 font-mono text-xs text-text">{e.eventType}</td>
                  <td className="px-5 py-3">
                    <span className="inline-flex items-center gap-1.5 text-xs text-text-muted">
                      <Icon size={13} />
                      {e.status}
                    </span>
                  </td>
                  <td className="px-5 py-3 tabular-nums text-text-muted">{e.attempts}</td>
                  <td className="px-5 py-3 tabular-nums text-text-muted">{e.latencyMs}ms</td>
                  <td className="px-5 py-3">
                    {e.signatureValid ? (
                      <span className="text-success">Valid</span>
                    ) : (
                      <span className="text-danger">Invalid</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-text-faint">{formatDateTime(e.receivedAt)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        </div>
      </GlassCard>

      <Modal open={!!selected} onClose={() => setSelected(null)} title={selected?.id ?? ''}>
        {selected && (
          <div className="flex flex-col gap-3 text-sm">
            <Row label="Event type" value={selected.eventType} />
            <Row label="Status" value={<StatusBadge status={selected.status} />} />
            <Row label="Attempts" value={String(selected.attempts)} />
            <Row label="Latency" value={`${selected.latencyMs}ms`} />
            <Row label="Signature" value={selected.signatureValid ? 'Valid (HMAC-SHA256)' : 'Invalid'} />
            <Row label="Received" value={formatDateTime(selected.receivedAt)} />
          </div>
        )}
      </Modal>
    </div>
  )
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-border/60 pb-2 last:border-0">
      <span className="text-text-muted">{label}</span>
      <span className="text-text">{value}</span>
    </div>
  )
}
