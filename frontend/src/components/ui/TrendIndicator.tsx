import { ArrowDown, ArrowUp } from 'lucide-react'
import clsx from 'clsx'

export function TrendIndicator({ value, label }: { value: number; label?: string }) {
  const positive = value >= 0
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-0.5 text-xs font-medium tabular-nums',
        positive ? 'text-success' : 'text-danger',
      )}
    >
      {positive ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
      {Math.abs(value).toFixed(1)}%{label && <span className="ml-1 text-text-faint">{label}</span>}
    </span>
  )
}
