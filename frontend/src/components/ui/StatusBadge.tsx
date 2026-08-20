import clsx from 'clsx'

const STATUS_STYLES: Record<string, string> = {
  CREATED: 'bg-black/[0.04] text-text-muted border-border',
  PROCESSING: 'bg-primary-soft text-primary border-primary/20',
  SUCCEEDED: 'bg-success-soft text-success border-success/20',
  FAILED: 'bg-danger-soft text-danger border-danger/20',
  UNKNOWN: 'bg-warning-soft text-warning border-warning/20',
  REFUND_PENDING: 'bg-secondary-soft text-secondary border-secondary/20',
  REFUND_FAILED: 'bg-danger-soft text-danger border-danger/20',
  REFUNDED: 'bg-secondary-soft text-secondary border-secondary/20',
  MATCHED: 'bg-success-soft text-success border-success/20',
  MISMATCH: 'bg-danger-soft text-danger border-danger/20',
  REQUIRES_ACTION: 'bg-warning-soft text-warning border-warning/20',
}

const DOT_STYLES: Record<string, string> = {
  SUCCEEDED: 'bg-success',
  MATCHED: 'bg-success',
  PROCESSING: 'bg-primary',
  FAILED: 'bg-danger',
  MISMATCH: 'bg-danger',
  REFUND_FAILED: 'bg-danger',
  UNKNOWN: 'bg-warning',
  REQUIRES_ACTION: 'bg-warning',
  REFUND_PENDING: 'bg-secondary',
  REFUNDED: 'bg-secondary',
  CREATED: 'bg-text-faint',
}

export function StatusBadge({ status }: { status: string }) {
  const classes = STATUS_STYLES[status] ?? 'bg-black/[0.04] text-text-muted border-border'
  const dot = DOT_STYLES[status] ?? 'bg-text-faint'
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-wide',
        classes,
      )}
    >
      <span className={clsx('h-1.5 w-1.5 rounded-full', dot)} />
      {status.replace(/_/g, ' ')}
    </span>
  )
}
