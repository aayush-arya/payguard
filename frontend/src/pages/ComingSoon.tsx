import { Sparkles } from 'lucide-react'
import { EmptyState } from '../components/ui'

/** Placeholder for nav sections with no backend yet (Refunds as its own
 * page, Analytics, Settings) -- an honest "not built yet" rather than a
 * page quietly full of fake numbers. See frontend/src/lib/mockData.ts's
 * header comment for which pages *do* use clearly-labeled mock data and
 * why these don't. */
export function ComingSoon({ title }: { title: string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <EmptyState
        icon={<Sparkles size={20} />}
        title={`${title} is coming soon`}
        description="This section needs a backend endpoint before it can show real data -- rather than fake it, it's not built yet."
      />
    </div>
  )
}
