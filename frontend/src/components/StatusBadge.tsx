const COLORS: Record<string, string> = {
  CREATED: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  PROCESSING: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  SUCCEEDED: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  FAILED: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  UNKNOWN: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  REFUND_PENDING: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  REFUND_FAILED: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  REFUNDED: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  MATCHED: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  MISMATCH: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
}

export function StatusBadge({ status }: { status: string }) {
  const classes = COLORS[status] ?? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${classes}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}
