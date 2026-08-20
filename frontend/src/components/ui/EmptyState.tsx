import { type ReactNode } from 'react'
import { motion } from 'framer-motion'

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center"
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-black/5 text-text-muted">
        {icon}
      </div>
      <p className="text-sm font-medium text-text">{title}</p>
      <p className="max-w-xs text-sm text-text-muted">{description}</p>
      {action}
    </motion.div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <EmptyState
      icon={<span className="text-lg">!</span>}
      title="Something went wrong"
      description={message}
      action={
        onRetry && (
          <button
            onClick={onRetry}
            className="mt-1 rounded-lg border border-border-strong px-3 py-1.5 text-xs font-medium text-text transition-colors hover:bg-black/5"
          >
            Try again
          </button>
        )
      }
    />
  )
}
