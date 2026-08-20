import { type ReactNode } from 'react'
import { motion, type HTMLMotionProps } from 'framer-motion'
import clsx from 'clsx'

interface GlassCardProps extends HTMLMotionProps<'div'> {
  children: ReactNode
  hoverLift?: boolean
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

const PADDING = { none: '', sm: 'p-4', md: 'p-5', lg: 'p-7' }

/** The one card primitive every page composes -- glassmorphism used once,
 * consistently, here, rather than each page inventing its own blur/border
 * combination (brief §36's "visual details" note). */
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
        'rounded-2xl border border-border bg-surface backdrop-blur-xl',
        'shadow-[0_1px_0_0_rgba(255,255,255,0.04)_inset,0_20px_40px_-24px_rgba(0,0,0,0.6)]',
        hoverLift && 'transition-shadow duration-300 hover:border-border-strong',
        PADDING[padding],
        className,
      )}
    >
      {children}
    </motion.div>
  )
}
