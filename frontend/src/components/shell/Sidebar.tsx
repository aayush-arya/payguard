import { NavLink } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import {
  LayoutDashboard,
  CreditCard,
  Undo2,
  ShieldAlert,
  GitCompareArrows,
  Webhook,
  BarChart3,
  Settings,
  ShieldCheck,
  Activity,
  X,
} from 'lucide-react'
import clsx from 'clsx'

interface NavItem {
  to: string
  label: string
  icon: typeof LayoutDashboard
  soon?: boolean
}

interface NavGroup {
  label: string
  items: NavItem[]
}

const GROUPS: NavGroup[] = [
  {
    label: 'Payments',
    items: [
      { to: '/', label: 'Overview', icon: LayoutDashboard },
      { to: '/payments', label: 'Payments', icon: CreditCard },
      { to: '/refunds', label: 'Refunds', icon: Undo2, soon: true },
    ],
  },
  {
    label: 'Protection',
    items: [
      { to: '/risk', label: 'Risk & Fraud', icon: ShieldAlert },
      { to: '/reconciliation', label: 'Reconciliation', icon: GitCompareArrows },
      { to: '/webhooks', label: 'Webhooks', icon: Webhook },
    ],
  },
  {
    label: 'Insights',
    items: [{ to: '/analytics', label: 'Analytics', icon: BarChart3, soon: true }],
  },
  {
    label: 'System',
    items: [
      { to: '/providers', label: 'Provider Health', icon: Activity },
      { to: '/settings', label: 'Settings', icon: Settings, soon: true },
    ],
  },
]

/** Static column on lg+ screens; below that it's an off-canvas drawer
 * (brief §31/§6 -- "collapsible" sidebar, "no horizontal overflow" on
 * mobile). One component handles both, rather than two divergent
 * sidebar implementations that could drift out of sync with each other's
 * nav items. */
export function Sidebar({ mobileOpen, onMobileClose }: { mobileOpen: boolean; onMobileClose: () => void }) {
  return (
    <>
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onMobileClose}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          />
        )}
      </AnimatePresence>

      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-50 flex h-screen w-64 shrink-0 flex-col border-r border-border bg-bg-elevated/95 backdrop-blur-xl transition-transform duration-300 lg:static lg:z-auto lg:w-60 lg:translate-x-0 lg:bg-bg-elevated/70',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-secondary text-white shadow-[0_0_20px_-4px_var(--color-primary)]">
            <ShieldCheck size={17} strokeWidth={2.25} />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-text">PayGuard</p>
            <p className="text-[10px] uppercase tracking-wider text-text-faint">Payment Infrastructure</p>
          </div>
          <button
            onClick={onMobileClose}
            aria-label="Close menu"
            className="ml-auto rounded-md p-1 text-text-muted hover:bg-white/5 lg:hidden"
          >
            <X size={16} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 pb-4">
        {GROUPS.map((group) => (
          <div key={group.label} className="mb-5">
            <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-wider text-text-faint">
              {group.label}
            </p>
            <div className="flex flex-col gap-0.5">
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  onClick={onMobileClose}
                  className={({ isActive }) =>
                    clsx(
                      'group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors',
                      isActive
                        ? 'bg-gradient-to-r from-primary-soft to-transparent text-text'
                        : 'text-text-muted hover:bg-white/[0.04] hover:text-text',
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && (
                        <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary shadow-[0_0_8px_var(--color-primary)]" />
                      )}
                      <item.icon size={16} strokeWidth={2} />
                      <span className="flex-1">{item.label}</span>
                      {item.soon && (
                        <span className="rounded-full bg-white/5 px-1.5 py-0.5 text-[9px] font-medium text-text-faint">
                          Soon
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
        </nav>
      </aside>
    </>
  )
}
