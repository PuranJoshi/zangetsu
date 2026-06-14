import { useCallback, useRef, useState } from "react"
import type {
  AdvisorResponse,
  ChangePlan,
  CouncilSession,
  FramedRequirement,
  ProjectContext,
} from "../types"
import { initialSession } from "../types"

export interface UseCouncilStreamResult {
  session: CouncilSession
  isRunning: boolean
  startCouncil: (
    planId: string,
    changeDescription: string,
    framedRequirement: FramedRequirement,
    projectContext?: ProjectContext | null,
    basePlanId?: string | null
  ) => Promise<void>
  /** Reset session state to advising (call before setPhase to avoid race). */
  prepareReview: () => void
  startReview: (
    planId: string,
    changeDescription: string,
    framedRequirement: FramedRequirement,
    feedback: string,
    projectContext?: ProjectContext | null,
    basePlanId?: string | null
  ) => Promise<void>
  loadFromPlan: (plan: ChangePlan) => void
  reset: () => void
}

export function useCouncilStream(): UseCouncilStreamResult {
  const [session, setSession] = useState<CouncilSession>(initialSession())
  const [isRunning, setIsRunning] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  const startCouncil = useCallback(
    async (
      planId: string,
      changeDescription: string,
      framedRequirement: FramedRequirement,
      projectContext?: ProjectContext | null,
      basePlanId?: string | null
    ) => {
      // Abort any existing stream
      if (abortRef.current) {
        abortRef.current.abort()
      }

      const controller = new AbortController()
      abortRef.current = controller

      setIsRunning(true)
      setSession({
        ...initialSession(),
        stage: "advising",
        planId,
      })

      try {
        const response = await fetch("/api/council/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: planId,
            change_description: changeDescription,
            framed_requirement: framedRequirement,
            project_context: projectContext ?? null,
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
              const event = JSON.parse(jsonStr)
              handleEvent(event)
            } catch {
              // Ignore parse errors in stream
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return
        setSession((prev) => ({
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

  const prepareReview = useCallback(() => {
    // Mark session as reviewing -- keeps existing plan visible
    // while the re-advise stream runs in the background.
    setSession((prev) => ({
      ...prev,
      stage: "reviewing",
      error: null,
    }))
  }, [])

  const startReview = useCallback(
    async (
      planId: string,
      changeDescription: string,
      framedRequirement: FramedRequirement,
      feedback: string,
      projectContext?: ProjectContext | null,
      basePlanId?: string | null
    ) => {
      // Abort any existing stream
      if (abortRef.current) {
        abortRef.current.abort()
      }

      const controller = new AbortController()
      abortRef.current = controller

      setIsRunning(true)
      // Keep stage as "reviewing" and keep the current plan visible.
      // The plan will be swapped in-place when synthesis completes.
      setSession((prev) => ({
        ...prev,
        stage: "reviewing",
        error: null,
      }))

      try {
        const response = await fetch("/api/council/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            plan_id: planId,
            change_description: changeDescription,
            framed_requirement: framedRequirement,
            project_context: projectContext ?? null,
            action: "re-advise",
            feedback,
            base_plan_id: basePlanId ?? null,
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
              const event = JSON.parse(jsonStr)
              handleEvent(event)
            } catch {
              // Ignore parse errors in stream
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return
        setSession((prev) => ({
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

    if (stage === "session" && status === "error") {
      setSession((prev) => ({
        ...prev,
        stage: "error",
        error: (data?.message as string) || "Pipeline error",
      }))
      return
    }

    if (stage === "session" && status === "started") {
      setSession((prev) => ({
        ...prev,
        // During a review, don't switch to "advising"
        stage: prev.stage === "reviewing" ? "reviewing" : "advising",
        planId: (data?.plan_id as string) || prev.planId,
      }))
      return
    }

    if (stage === "advisors" && status === "started") {
      setSession((prev) => ({
        ...prev,
        advisorNames: (data?.advisor_names as string[]) || [],
      }))
      return
    }

    if (stage === "advisor" && status === "completed") {
      const advisor: AdvisorResponse = {
        name: data?.name as string,
        response: data?.response as string,
      }
      setSession((prev) => ({
        ...prev,
        advisorResponses: [...prev.advisorResponses, advisor],
      }))
      return
    }

    if (stage === "synthesis" && status === "started") {
      setSession((prev) => ({
        ...prev,
        // During a review, don't switch to "synthesizing" -- keep "reviewing"
        stage: prev.stage === "reviewing" ? "reviewing" : "synthesizing",
      }))
      return
    }

    if (stage === "synthesis" && status === "completed") {
      setSession((prev) => ({
        ...prev,
        plan: data?.plan as ChangePlan,
      }))
      return
    }

    if (stage === "session" && status === "completed") {
      setSession((prev) => ({
        ...prev,
        stage: "completed",
        duration: (data?.duration as number) || null,
      }))
      return
    }

    // Review-specific events (from /council/review endpoint)
    if (stage === "review" && status === "started") {
      // Keep "reviewing" -- user stays on plan view
      setSession((prev) => ({
        ...prev,
        stage: "reviewing",
      }))
      return
    }

    if (stage === "review" && status === "approved") {
      setSession((prev) => ({ ...prev, stage: "completed" }))
      return
    }

    if (stage === "review" && status === "rejected") {
      setSession((prev) => ({ ...prev, stage: "completed" }))
      return
    }
  }

  const loadFromPlan = useCallback((plan: ChangePlan) => {
    // Hydrate session state from a saved plan (loaded from history)
    const advisorResponses: AdvisorResponse[] = Object.entries(
      plan.raw_advisor_responses || {}
    ).map(([name, response]) => ({ name, response }))

    setSession({
      stage: "completed",
      planId: plan.plan_id,
      advisorNames: advisorResponses.map((a) => a.name),
      advisorResponses,
      plan,
      duration: null,
      error: null,
    })
    setIsRunning(false)
  }, [])

  const reset = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    setSession(initialSession())
    setIsRunning(false)
  }, [])

  return { session, isRunning, startCouncil, prepareReview, startReview, loadFromPlan, reset }
}
