import { useCallback, useRef, useState } from "react"
import type {
  AdvisorReview,
  ChangePlan,
  CouncilDecision,
  CouncilFeedbackStage,
  CouncilFeedbackState,
  FramedRequirement,
  ProjectContext,
  StageTokenUsage,
  TokenUsageData,
  TokenUsageState,
} from "../types"

/**
 * Convert frontend TokenUsageState to the backend dict format
 * expected by TokenTracker.from_dict().
 */
function tokenUsageStateToDict(state: TokenUsageState): Record<string, unknown> {
  const stages: Record<string, TokenUsageData> = {}
  for (const s of state.stages) {
    stages[s.stage] = s.usage
  }
  return { stages, total: state.total }
}

export interface UseCouncilFeedbackResult {
  state: CouncilFeedbackState
  isRunning: boolean
  isApplying: boolean
  requestFeedback: (planId: string, plan: ChangePlan, priorTokenUsage?: TokenUsageState | null) => Promise<void>
  applyChanges: (
    planId: string,
    changeDescription: string,
    framedRequirement: FramedRequirement,
    acceptedChanges: string[],
    projectContext?: ProjectContext | null,
    basePlanId?: string | null,
    priorTokenUsage?: TokenUsageState | null
  ) => Promise<ChangePlan | null>
  reset: () => void
}

function initialState(): CouncilFeedbackState {
  return {
    stage: "idle",
    advisorReviews: [],
    decision: null,
    error: null,
    tokenUsage: null,
  }
}

export function useCouncilFeedback(): UseCouncilFeedbackResult {
  const [state, setState] = useState<CouncilFeedbackState>(initialState())
  const [isRunning, setIsRunning] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const requestFeedback = useCallback(
    async (planId: string, plan: ChangePlan, priorTokenUsage?: TokenUsageState | null) => {
      if (abortRef.current) {
        abortRef.current.abort()
      }

      const controller = new AbortController()
      abortRef.current = controller

      setIsRunning(true)
      setState({
        stage: "reviewing",
        advisorReviews: [],
        decision: null,
        error: null,
        tokenUsage: null,
      })

      try {
        const priorDict = priorTokenUsage ? tokenUsageStateToDict(priorTokenUsage) : null

        const response = await fetch("/api/council/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: planId,
            plan_data: plan,
            prior_token_usage: priorDict,
          }),
          signal: controller.signal,
        })

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}))
          throw new Error(errData.error || `HTTP ${response.status}`)
        }

        const reader = response.body?.getReader()
        if (!reader) throw new Error("No response body")

        const decoder = new TextDecoder()
        let buffer = ""

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split("\n")
          buffer = lines.pop() || ""

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue
            const jsonStr = line.slice(6).trim()
            if (!jsonStr) continue

            try {
              const event = JSON.parse(jsonStr) as {
                stage: string
                status: string
                data?: Record<string, unknown>
              }
              handleEvent(event)
            } catch {
              // Ignore parse errors
            }
          }
        }

        // Mark completed if not already errored
        setState((prev) =>
          prev.stage === "error" ? prev : { ...prev, stage: "completed" }
        )
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return
        setState((prev) => ({
          ...prev,
          stage: "error",
          error: err instanceof Error ? err.message : "Unknown error",
        }))
      } finally {
        setIsRunning(false)
        abortRef.current = null
      }
    },
    []
  )

  function handleEvent(event: {
    stage: string
    status: string
    data?: Record<string, unknown>
  }) {
    const { stage, status, data } = event

    if (stage === "feedback" && status === "error") {
      setState((prev) => ({
        ...prev,
        stage: "error",
        error: (data?.message as string) || "Feedback error",
      }))
      return
    }

    if (stage === "feedback" && status === "advisor") {
      const review: AdvisorReview = {
        name: data?.name as string,
        review: data?.review as string,
      }
      setState((prev) => ({
        ...prev,
        advisorReviews: [...prev.advisorReviews, review],
      }))
      return
    }

    if (stage === "feedback" && status === "deciding") {
      setState((prev) => ({
        ...prev,
        stage: "deciding" as CouncilFeedbackStage,
      }))
      return
    }

    if (stage === "feedback" && status === "decision") {
      // Extract token_usage from the decision event if present
      const tu = data?.token_usage as
        | { stages: Record<string, TokenUsageData>; total: TokenUsageData }
        | undefined
      let feedbackTokenUsage: TokenUsageState | null = null
      if (tu) {
        feedbackTokenUsage = {
          stages: Object.entries(tu.stages).map(
            ([name, usage]) => ({ stage: name, usage }) as StageTokenUsage
          ),
          total: tu.total,
        }
      }
      setState((prev) => ({
        ...prev,
        stage: "completed" as CouncilFeedbackStage,
        decision: data?.decision as CouncilDecision,
        tokenUsage: feedbackTokenUsage || prev.tokenUsage,
      }))
      return
    }

    // token_usage events emitted by /council/feedback and /council/feedback/apply
    if (stage === "token_usage" && status === "update") {
      const stageName = data?.stage as string
      const usage = data?.usage as TokenUsageData
      const total = data?.total as TokenUsageData
      if (stageName && usage && total) {
        setState((prev) => {
          const existing = prev.tokenUsage?.stages || []
          const idx = existing.findIndex((s) => s.stage === stageName)
          const updated =
            idx >= 0
              ? existing.map((s, i) => (i === idx ? { stage: stageName, usage } : s))
              : [...existing, { stage: stageName, usage }]
          return {
            ...prev,
            tokenUsage: { stages: updated, total },
          }
        })
      }
      return
    }
  }

  const applyChanges = useCallback(
    async (
      planId: string,
      changeDescription: string,
      framedRequirement: FramedRequirement,
      acceptedChanges: string[],
      projectContext?: ProjectContext | null,
      basePlanId?: string | null,
      priorTokenUsage?: TokenUsageState | null
    ): Promise<ChangePlan | null> => {
      if (abortRef.current) {
        abortRef.current.abort()
      }

      const controller = new AbortController()
      abortRef.current = controller

      setIsApplying(true)
      let resultPlan: ChangePlan | null = null
      let newPlanId: string | null = null
      let newBasePlanId: string | null = null

      try {
        const priorDict = priorTokenUsage ? tokenUsageStateToDict(priorTokenUsage) : null

        const response = await fetch("/api/council/feedback/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: planId,
            change_description: changeDescription,
            framed_requirement: framedRequirement,
            accepted_changes: acceptedChanges,
            project_context: projectContext ?? null,
            base_plan_id: basePlanId ?? null,
            prior_token_usage: priorDict,
          }),
          signal: controller.signal,
        })

        if (!response.ok) {
          const errData = await response.json().catch(() => ({}))
          throw new Error(errData.error || `HTTP ${response.status}`)
        }

        const reader = response.body?.getReader()
        if (!reader) throw new Error("No response body")

        const decoder = new TextDecoder()
        let buffer = ""

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split("\n")
          buffer = lines.pop() || ""

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue
            const jsonStr = line.slice(6).trim()
            if (!jsonStr) continue

            try {
              const event = JSON.parse(jsonStr) as {
                stage: string
                status: string
                data?: Record<string, unknown>
              }
              // Capture new plan_id from session/started (server generates it)
              if (event.stage === "session" && event.status === "started") {
                if (event.data?.plan_id) newPlanId = event.data.plan_id as string
                if (event.data?.base_plan_id) newBasePlanId = event.data.base_plan_id as string
              }
              // Capture the new plan from synthesis/completed
              if (
                event.stage === "synthesis" &&
                event.status === "completed" &&
                event.data?.plan
              ) {
                resultPlan = event.data.plan as ChangePlan
              }
              // Capture final plan_id from session/completed
              if (event.stage === "session" && event.status === "completed") {
                if (event.data?.plan_id) newPlanId = event.data.plan_id as string
                if (event.data?.base_plan_id) newBasePlanId = event.data.base_plan_id as string
              }
              if (event.stage === "session" && event.status === "error") {
                throw new Error(
                  (event.data?.message as string) || "Apply error"
                )
              }
              // Forward token_usage events to feedback state
              if (event.stage === "token_usage" && event.status === "update") {
                handleEvent(event)
              }
            } catch (e) {
              if (e instanceof Error && e.message !== "Apply error") {
                // Ignore JSON parse errors
              } else {
                throw e
              }
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return null
        setState((prev) => ({
          ...prev,
          stage: "error",
          error: err instanceof Error ? err.message : "Unknown error",
        }))
        return null
      } finally {
        setIsApplying(false)
        abortRef.current = null
      }

      // Stamp the server-generated plan_id and base_plan_id onto the
      // result so the caller can update session state correctly.
      if (resultPlan) {
        if (newPlanId) resultPlan.plan_id = newPlanId
        if (newBasePlanId) resultPlan.base_plan_id = newBasePlanId
      }

      return resultPlan
    },
    []
  )

  const reset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    setState(initialState())
    setIsRunning(false)
    setIsApplying(false)
  }, [])

  return { state, isRunning, isApplying, requestFeedback, applyChanges, reset }
}
