import { type ReactNode } from 'react'
import { motion, type HTMLMotionProps } from 'framer-motion'
import clsx from 'clsx'

interface GlassCardProps extends HTMLMotionProps<'div'> {
  children: ReactNode
  hoverLift?: boolean
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

const PADDING = { none: '', sm: 'p-4', md: 'p-5', lg: 'p-7' }

/** The one card primitive every page composes -- a soft, flat, warm card
 * used once, consistently, here, rather than each page inventing its own
 * border/shadow combination (brief §36's "visual details" note). */
export function GlassCard({
  children,
  className,
  hoverLift = false,
  padding = 'md',
  ...rest
}: GlassCardProps) {
  return (
    <motion.div
      {...rest}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      whileHover={hoverLift ? { y: -2 } : undefined}
      className={clsx(
        'rounded-3xl border border-border bg-surface',
        'shadow-[0_2px_8px_-2px_rgba(27,23,18,0.06),0_16px_28px_-18px_rgba(27,23,18,0.12)]',
        hoverLift && 'transition-shadow duration-300 hover:border-border-strong hover:shadow-[0_4px_14px_-2px_rgba(27,23,18,0.1),0_20px_32px_-16px_rgba(27,23,18,0.14)]',
        PADDING[padding],
        className,
      )}
    >
      {children}
    </motion.div>
  )
}
