import { useEffect, useState } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from 'react-router-dom'
import {
  CreditCard,
  GitCompareArrows,
  LayoutDashboard,
  Plus,
  Settings,
  ShieldAlert,
  Webhook,
} from 'lucide-react'
import { listPayments } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { formatAmount } from '../../lib/format'

/** ⌘K command palette -- keyboard-native via cmdk. Searches real payments
 * (id/reference) against the live API; static commands navigate the app.
 * This is the one place "search anything" in the redesign brief is
 * implemented against real data rather than mocked -- payments are the
 * one entity this backend can actually look up. */
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const navigate = useNavigate()
  const { apiKey } = useAuth()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<{ id: string; label: string; amount: string }[]>([])

  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  useEffect(() => {
    if (!apiKey || query.trim().length < 2) {
      setResults([])
      return
    }
    const handle = setTimeout(() => {
      listPayments(apiKey, { limit: 50 })
        .then((res) => {
          const q = query.trim().toLowerCase()
          setResults(
            res.items
              .filter(
                (p) => p.id.toLowerCase().includes(q) || p.merchant_reference?.toLowerCase().includes(q),
              )
              .slice(0, 6)
              .map((p) => ({ id: p.id, label: p.merchant_reference ?? p.id, amount: formatAmount(p.amount, p.currency) })),
          )
        })
        .catch(() => setResults([]))
    }, 200)
    return () => clearTimeout(handle)
  }, [query, apiKey])

  function go(path: string) {
    navigate(path)
    onOpenChange(false)
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={onOpenChange}
      label="Command palette"
      shouldFilter={false}
      className="fixed left-1/2 top-24 z-50 w-full max-w-lg -translate-x-1/2 overflow-hidden rounded-2xl border border-border bg-surface-solid shadow-xl"
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search anything..."
          className="w-full bg-transparent text-sm text-text placeholder:text-text-faint focus:outline-none"
        />
        <kbd className="rounded border border-border px-1.5 py-0.5 text-[10px] text-text-faint">esc</kbd>
      </div>
      <Command.List className="max-h-80 overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-sm text-text-muted">
          No results.
        </Command.Empty>

        {results.length > 0 && (
          <Command.Group heading="Payments" className="px-1 py-1 text-[10px] uppercase tracking-wider text-text-faint">
            {results.map((r) => (
              <Command.Item
                key={r.id}
                onSelect={() => go(`/payments/${r.id}`)}
                className="flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]"
              >
                <span className="flex items-center gap-2">
                  <CreditCard size={14} className="text-text-faint" />
                  {r.label}
                </span>
                <span className="text-text-muted tabular-nums">{r.amount}</span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        <Command.Group heading="Go to" className="px-1 py-1 text-[10px] uppercase tracking-wider text-text-faint">
          <Command.Item onSelect={() => go('/')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]">
            <LayoutDashboard size={14} className="text-text-faint" /> Overview
          </Command.Item>
          <Command.Item onSelect={() => go('/payments')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]">
            <CreditCard size={14} className="text-text-faint" /> Payments
          </Command.Item>
          <Command.Item onSelect={() => go('/risk')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]">
            <ShieldAlert size={14} className="text-text-faint" /> Risk & Fraud
          </Command.Item>
          <Command.Item onSelect={() => go('/reconciliation')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]">
            <GitCompareArrows size={14} className="text-text-faint" /> Reconciliation
          </Command.Item>
          <Command.Item onSelect={() => go('/webhooks')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]">
            <Webhook size={14} className="text-text-faint" /> Webhooks
          </Command.Item>
          <Command.Item onSelect={() => go('/settings')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]">
            <Settings size={14} className="text-text-faint" /> Settings
          </Command.Item>
        </Command.Group>

        <Command.Group heading="Actions" className="px-1 py-1 text-[10px] uppercase tracking-wider text-text-faint">
          <Command.Item onSelect={() => go('/payments?new=1')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-text data-[selected=true]:bg-black/[0.05]">
            <Plus size={14} className="text-text-faint" /> Create payment
          </Command.Item>
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  )
}
