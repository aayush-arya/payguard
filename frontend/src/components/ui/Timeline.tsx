import { type ReactNode } from 'react'
import { motion } from 'framer-motion'
import clsx from 'clsx'

export interface TimelineItem {
  id: string
  icon: ReactNode
  title: string
  subtitle?: string
  meta?: string
  tone?: 'success' | 'warning' | 'danger' | 'default'
}

const TONE_RING: Record<string, string> = {
  success: 'border-success/30 bg-success-soft text-success',
  warning: 'border-warning/30 bg-warning-soft text-warning',
  danger: 'border-danger/30 bg-danger-soft text-danger',
  default: 'border-border-strong bg-black/5 text-text-muted',
}

export function Timeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="relative flex flex-col gap-5 pl-1">
      {items.map((item, i) => (
        <motion.li
          key={item.id}
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.25, delay: i * 0.03 }}
          className="relative flex gap-3 pl-8"
        >
          {i < items.length - 1 && (
            <span className="absolute left-[15px] top-8 h-[calc(100%-8px)] w-px bg-border" />
          )}
          <span
            className={clsx(
              'absolute left-0 top-0 flex h-8 w-8 items-center justify-center rounded-full border',
              TONE_RING[item.tone ?? 'default'],
            )}
          >
            {item.icon}
          </span>
          <div className="flex-1 pb-0.5">
            <p className="text-sm font-medium text-text">{item.title}</p>
            {item.subtitle && <p className="mt-0.5 text-xs text-text-muted">{item.subtitle}</p>}
          </div>
          {item.meta && <span className="shrink-0 text-xs text-text-faint tabular-nums">{item.meta}</span>}
        </motion.li>
      ))}
    </ol>
  )
}
