import { useState } from 'react'
import { Bell, Menu, Search } from 'lucide-react'
import { useAuth } from '../../lib/auth'

export function TopBar({
  onOpenCommandPalette,
  onOpenSidebar,
}: {
  onOpenCommandPalette: () => void
  onOpenSidebar: () => void
}) {
  const { disconnect } = useAuth()
  const [envOpen, setEnvOpen] = useState(false)
  const isMac = typeof navigator !== 'undefined' && navigator.userAgent.includes('Mac')

  return (
    <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center gap-3 border-b border-border bg-bg/70 px-4 backdrop-blur-xl sm:gap-4 sm:px-6">
      <button
        onClick={onOpenSidebar}
        aria-label="Open menu"
        className="rounded-md p-1.5 text-text-muted hover:bg-white/5 lg:hidden"
      >
        <Menu size={18} />
      </button>

      <button
        onClick={onOpenCommandPalette}
        className="flex w-full max-w-sm items-center gap-2 rounded-lg border border-border bg-white/[0.03] px-3 py-2 text-sm text-text-faint transition-colors hover:border-border-strong hover:text-text-muted"
      >
        <Search size={14} />
        <span className="flex-1 truncate text-left">Search anything...</span>
        <kbd className="hidden rounded border border-border px-1.5 py-0.5 text-[10px] sm:inline">
          {isMac ? '⌘K' : 'Ctrl K'}
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-3">
        <div className="relative">
          <button
            onClick={() => setEnvOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-xs text-text-muted transition-colors hover:border-border-strong"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-success shadow-[0_0_6px_var(--color-success)]" />
            Production
          </button>
          {envOpen && (
            <div className="absolute right-0 top-full mt-2 w-40 rounded-xl border border-border bg-surface-solid p-1 shadow-2xl">
              {['Production', 'Staging', 'Development'].map((env) => (
                <button
                  key={env}
                  onClick={() => setEnvOpen(false)}
                  className="block w-full rounded-lg px-3 py-2 text-left text-xs text-text-muted hover:bg-white/5 hover:text-text"
                >
                  {env}
                </button>
              ))}
            </div>
          )}
        </div>

        <button
          aria-label="Notifications"
          className="relative flex h-8 w-8 items-center justify-center rounded-lg text-text-muted transition-colors hover:bg-white/5 hover:text-text"
        >
          <Bell size={16} />
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-danger" />
        </button>

        <button
          onClick={disconnect}
          className="flex items-center gap-2 rounded-lg border border-border px-2 py-1.5 transition-colors hover:border-border-strong"
        >
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-br from-primary to-secondary text-[10px] font-semibold text-white">
            A
          </span>
          <span className="text-xs text-text-muted">Admin</span>
        </button>
      </div>
    </header>
  )
}
