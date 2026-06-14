import { useCallback, useEffect, useState } from "react"
import type { ChangePlan, FramedRequirement, PlanSummary } from "../types"
import { useRoute } from "../hooks/useRoute"
import { PlanView } from "./PlanView"

// ---------------------------------------------------------------------------
// Plan detail view -- fetches and displays a full plan by ID
// ---------------------------------------------------------------------------

function PlanDetail({
  planId,
  onBack,
  onLoad,
}: {
  planId: string
  onBack: () => void
  onLoad: (plan: ChangePlan, description: string, framedRequirement?: FramedRequirement) => void
}) {
  const [plan, setPlan] = useState<ChangePlan | null>(null)
  const [description, setDescription] = useState("")
  const [framedReq, setFramedReq] = useState<FramedRequirement | undefined>(undefined)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetch(`/api/plans/${planId}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`Plan not found (${res.status})`)
        return res.json()
      })
      .then((data) => {
        if (cancelled) return
        // The saved plan JSON has { plan: {...}, change_description, ... }
        const planData = data.plan as ChangePlan
        if (planData) {
          // Ensure plan_id and change_description are set from outer wrapper
          planData.plan_id = planData.plan_id || data.plan_id || planId
          planData.change_description =
            planData.change_description || data.change_description || ""
          // Carry base_plan_id from the outer wrapper into the plan object
          if (!planData.base_plan_id && data.base_plan_id) {
            planData.base_plan_id = data.base_plan_id
          }
          // Merge raw_advisor_responses from the outer data if not on the plan
          if (
            (!planData.raw_advisor_responses ||
              Object.keys(planData.raw_advisor_responses).length === 0) &&
            data.advisor_responses
          ) {
            planData.raw_advisor_responses = data.advisor_responses
          }
          setPlan(planData)
          setDescription(data.change_description || "")
          // Extract framed_requirement from the saved plan data
          if (data.framed_requirement) {
            setFramedReq(data.framed_requirement as FramedRequirement)
          }
        } else {
          setError("Plan data is empty")
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [planId])

  if (loading) {
    return (
      <div className="py-12 text-center text-text-muted text-sm">
        Loading plan...
      </div>
    )
  }

  if (error || !plan) {
    return (
      <div className="py-12 text-center">
        <p className="text-sm text-red-500">{error || "Plan not found"}</p>
        <button
          onClick={onBack}
          className="mt-3 text-sm text-accent hover:underline"
        >
          Back to history
        </button>
      </div>
    )
  }

  return (
    <PlanView
      plan={plan}
      duration={null}
      onBack={onBack}
      onLoadIntoSession={() => onLoad(plan, description, framedReq)}
    />
  )
}

// ---------------------------------------------------------------------------
// Plan list view
// ---------------------------------------------------------------------------

function PlanList({ onSelectPlan }: { onSelectPlan: (id: string) => void }) {
  const [plans, setPlans] = useState<PlanSummary[]>([])
  const [loading, setLoading] = useState(true)
  const { navigate } = useRoute()

  const fetchPlans = useCallback(async () => {
    try {
      const res = await fetch("/api/plans?limit=30")
      if (res.ok) {
        const data = await res.json()
        setPlans(data)
      }
    } catch {
      // Silent fail
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchPlans()
  }, [fetchPlans])

  if (loading) {
    return (
      <div className="py-12 text-center text-text-muted text-sm">
        Loading plans...
      </div>
    )
  }

  if (plans.length === 0) {
    return (
      <div className="py-12 text-center">
        <p className="text-text-muted text-sm">No plans yet.</p>
        <button
          onClick={() => navigate("/")}
          className="mt-3 text-sm text-accent hover:underline"
        >
          Create your first plan
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3 py-6 px-4 max-w-2xl mx-auto w-full">
      <h2 className="text-lg font-medium text-text-primary">Recent Plans</h2>

      <div className="space-y-2">
        {plans.map((plan) => (
          <button
            key={plan.plan_id}
            onClick={() => onSelectPlan(plan.plan_id)}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-lg
                       border border-border hover:border-text-muted
                       hover:bg-surface-secondary transition-colors text-left"
          >
            <div className="flex-1 min-w-0">
              <p className="text-sm text-text-primary truncate">
                {plan.change_description || plan.plan_id}
              </p>
              <p className="text-xs text-text-muted mt-0.5">
                {new Date(plan.timestamp).toLocaleDateString()} &middot;{" "}
                <span className="font-mono">{plan.plan_id}</span>
              </p>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {plan.risk_level && (
                <span
                  className={`px-1.5 py-0.5 text-xs rounded ${
                    plan.risk_level === "HIGH"
                      ? "bg-red-500/10 text-red-500"
                      : plan.risk_level === "MEDIUM"
                        ? "bg-amber-500/10 text-amber-500"
                        : "bg-green-500/10 text-green-500"
                  }`}
                >
                  {plan.risk_level}
                </span>
              )}
              {plan.effort && (
                <span className="px-1.5 py-0.5 text-xs rounded bg-accent/10 text-accent">
                  {plan.effort}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// PlanHistory -- combines list + detail views
//
// Plan detail is managed by component state (selectedPlanId), not by URL.
// Only /history is a URL route; clicking a plan sets local state.
// ---------------------------------------------------------------------------

interface Props {
  onLoadPlan: (plan: ChangePlan, description: string, framedRequirement?: FramedRequirement) => void
}

export function PlanHistory({ onLoadPlan }: Props) {
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null)

  if (selectedPlanId) {
    return (
      <PlanDetail
        planId={selectedPlanId}
        onBack={() => setSelectedPlanId(null)}
        onLoad={onLoadPlan}
      />
    )
  }

  return <PlanList onSelectPlan={setSelectedPlanId} />
}
