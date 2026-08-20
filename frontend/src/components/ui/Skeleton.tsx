import clsx from 'clsx'

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={clsx(
        'animate-pulse rounded-md bg-gradient-to-r from-white/[0.04] via-white/[0.08] to-white/[0.04] bg-[length:200%_100%]',
        className,
      )}
      style={{ animation: 'shimmer 1.6s ease-in-out infinite' }}
    />
  )
}

export function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <Skeleton className="h-8 w-8 rounded-lg" />
      <Skeleton className="mt-4 h-6 w-20" />
      <Skeleton className="mt-2 h-3 w-28" />
    </div>
  )
}

export function SkeletonRow({ columns = 5 }: { columns?: number }) {
  return (
    <tr>
      {Array.from({ length: columns }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <Skeleton className="h-4 w-full max-w-24" />
        </td>
      ))}
    </tr>
  )
}
