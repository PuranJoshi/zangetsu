import { useCallback, useEffect, useState } from "react"
import type { PlanSummary } from "../types"

// ---------------------------------------------------------------------------
// Status badge colour mapping
// ---------------------------------------------------------------------------

function statusStyle(status: string): { bg: string; text: string; label: string } {
  const s = status?.toUpperCase() || ""
  switch (s) {
    case "FRAMING":
    case "DRAFTING":
      return { bg: "bg-amber-500/15", text: "text-amber-500", label: s }
    case "PROPOSED":
      return { bg: "bg-blue-500/15", text: "text-blue-500", label: s }
    case "REVIEWING":
      return { bg: "bg-purple-500/15", text: "text-purple-500", label: s }
    case "AGREED":
    case "COMPLETED":
    case "COUNCIL_REVIEWED":
      return { bg: "bg-green-500/15", text: "text-green-500", label: s === "COUNCIL_REVIEWED" ? "REVIEWED" : s }
    case "REJECTED":
      return { bg: "bg-red-500/15", text: "text-red-500", label: s }
    case "STALLED":
      return { bg: "bg-orange-500/15", text: "text-orange-500", label: s }
    default:
      return { bg: "bg-text-muted/10", text: "text-text-muted", label: s || "UNKNOWN" }
  }
}

// ---------------------------------------------------------------------------
// Relative time helper
// ---------------------------------------------------------------------------

function relativeTime(iso: string): string {
  const now = Date.now()
  const then = new Date(iso).getTime()
  const diffMs = now - then
  const diffMin = Math.floor(diffMs / 60_000)
  if (diffMin < 1) return "just now"
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 7) return `${diffDay}d ago`
  return new Date(iso).toLocaleDateString()
}

// ---------------------------------------------------------------------------
// PlanSidebar
// ---------------------------------------------------------------------------

interface Props {
  /** ID of the plan currently loaded in the main view (if any) */
  activePlanId: string | null
  /** Called when the user clicks a plan in the sidebar */
  onSelectPlan: (planId: string) => void
  /** Increment this counter to trigger a re-fetch of plans */
  refreshKey: number
}

export function PlanSidebar({ activePlanId, onSelectPlan, refreshKey }: Props) {
  const [plans, setPlans] = useState<PlanSummary[]>([])
  const [loading, setLoading] = useState(true)

  const fetchPlans = useCallback(async () => {
    try {
      const res = await fetch("/api/plans?limit=30")
      if (res.ok) {
        const data = await res.json()
        setPlans(data)
      }
    } catch {
      // Silent fail -- sidebar is non-critical
    } finally {
      setLoading(false)
    }
  }, [])

  // Fetch on mount and whenever refreshKey changes
  useEffect(() => {
    fetchPlans()
  }, [fetchPlans, refreshKey])

  return (
    <aside className="plan-sidebar flex flex-col border-r border-border bg-surface-secondary">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          Plans
        </span>
        {plans.length > 0 && (
          <span className="text-[10px] text-text-muted bg-surface-tertiary rounded-full px-1.5 py-0.5 font-mono">
            {plans.length}
          </span>
        )}
      </div>

      {/* Plan list */}
      <div className="flex-1 overflow-y-auto scroll-on-hover">
        {loading ? (
          <div className="px-3 py-6 text-center text-text-muted text-xs">
            Loading...
          </div>
        ) : plans.length === 0 ? (
          <div className="px-3 py-6 text-center text-text-muted text-xs">
            No plans yet
          </div>
        ) : (
          <div className="py-1">
            {plans.map((plan) => {
              const isActive = plan.plan_id === activePlanId
              const style = statusStyle(plan.status)

              return (
                <button
                  key={plan.plan_id}
                  onClick={() => onSelectPlan(plan.plan_id)}
                  className={`
                    w-full text-left px-3 py-2 transition-colors
                    border-l-2
                    ${
                      isActive
                        ? "border-l-accent bg-accent/8 text-text-primary"
                        : "border-l-transparent hover:bg-surface-tertiary text-text-secondary hover:text-text-primary"
                    }
                  `}
                >
                  {/* Description */}
                  <p className="text-xs leading-snug truncate">
                    {plan.change_description || plan.plan_id}
                  </p>

                  {/* Meta row: status badge + timestamp */}
                  <div className="flex items-center gap-1.5 mt-1">
                    <span
                      className={`inline-block px-1 py-px text-[10px] font-medium rounded ${style.bg} ${style.text}`}
                    >
                      {style.label}
                    </span>
                    <span className="text-[10px] text-text-muted">
                      {relativeTime(plan.timestamp)}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </aside>
  )
}
