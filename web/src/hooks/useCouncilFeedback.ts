import { useCallback, useRef, useState } from "react"
import type {
  AdvisorReview,
  ChangePlan,
  CouncilDecision,
  CouncilFeedbackStage,
  CouncilFeedbackState,
} from "../types"

export interface UseCouncilFeedbackResult {
  state: CouncilFeedbackState
  isRunning: boolean
  requestFeedback: (planId: string, plan: ChangePlan) => Promise<void>
  reset: () => void
}

function initialState(): CouncilFeedbackState {
  return {
    stage: "idle",
    advisorReviews: [],
    decision: null,
    error: null,
  }
}

export function useCouncilFeedback(): UseCouncilFeedbackResult {
  const [state, setState] = useState<CouncilFeedbackState>(initialState())
  const [isRunning, setIsRunning] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const requestFeedback = useCallback(
    async (planId: string, plan: ChangePlan) => {
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
      })

      try {
        const response = await fetch("/api/council/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: planId,
            plan_data: plan,
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
      setState((prev) => ({
        ...prev,
        stage: "completed" as CouncilFeedbackStage,
        decision: data?.decision as CouncilDecision,
      }))
      return
    }
  }

  const reset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    setState(initialState())
    setIsRunning(false)
  }, [])

  return { state, isRunning, requestFeedback, reset }
}
