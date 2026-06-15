import { useState, useCallback, useRef, useEffect } from "react"
import type { FramedRequirement, ProjectContext, ChangePlan } from "./types"
import { useFramer } from "./hooks/useFramer"
import { useCouncilStream } from "./hooks/useCouncilStream"
import { useCouncilFeedback } from "./hooks/useCouncilFeedback"
import { useProjectScan } from "./hooks/useProjectScan"
import { useRoute } from "./hooks/useRoute"
import { DescriptionInput } from "./components/DescriptionInput"
import { FramerWizard } from "./components/FramerWizard"
import { RequirementReview } from "./components/RequirementReview"
import { ProjectScanner } from "./components/ProjectScanner"
import { AdvisorsPanel } from "./components/AdvisorsPanel"
import { PipelineTracker } from "./components/PipelineTracker"
import { PlanView } from "./components/PlanView"
import { PlanHistory } from "./components/PlanHistory"
import { PlanSidebar } from "./components/PlanSidebar"
import { ErrorDisplay } from "./components/ErrorDisplay"

// ---------------------------------------------------------------------------
// Wizard phases
// ---------------------------------------------------------------------------

type Phase =
  | "input"
  | "framing"
  | "reviewing"
  | "scanning"
  | "advising"
  | "done"

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

export default function App() {
  const route = useRoute()

  // Wizard state
  const [phase, setPhase] = useState<Phase>("input")
  const [rawDescription, setRawDescription] = useState("")
  const [framedRequirement, setFramedRequirement] =
    useState<FramedRequirement | null>(null)
  const [projectContext, setProjectContext] = useState<ProjectContext | null>(null)
  const [planId, setPlanId] = useState<string | null>(null)
  const [basePlanId, setBasePlanId] = useState<string | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [_reviewVersion, setReviewVersion] = useState(1)
  const [isReframing, setIsReframing] = useState(false)
  const [reAdviseError, setReAdviseError] = useState<string | null>(null)
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0)

  // Track whether the user has an active session (not idle input)
  const hasActiveSession = phase !== "input"

  // Hooks
  const framer = useFramer()
  const council = useCouncilStream()
  const councilFeedback = useCouncilFeedback()
  const scanner = useProjectScan()

  // Guard against duplicate phase transitions during a single render
  const phaseRef = useRef(phase)
  useEffect(() => {
    phaseRef.current = phase
  }, [phase])

  // ---------------------------------------------------------------------------
  // Phase transitions
  // ---------------------------------------------------------------------------

  const handleDescriptionSubmit = useCallback(
    (description: string) => {
      setRawDescription(description)
      setPhase("framing")
      framer.startFraming(description)
    },
    [framer]
  )

  const handleLoadTranscript = useCallback(
    async (transcriptPlanId: string) => {
      try {
        const res = await fetch(`/api/transcripts/${transcriptPlanId}`)
        if (!res.ok) return
        const data = await res.json()

        const question = data.question || ""
        setRawDescription(question)

        // Build context from the transcript for the framer
        const parts: string[] = []
        parts.push(`Original request: ${question}`)

        // Include framer Q&A history
        const messages = data.framer_messages || []
        if (messages.length > 0) {
          parts.push("")
          parts.push("=== Previous Framing Conversation ===")
          for (const msg of messages) {
            const role = msg.role === "framer" ? "Framer" : "User"
            parts.push(`${role}: ${msg.text}`)
          }
          parts.push("=== End Conversation ===")
        }

        if (data.framed_question) {
          parts.push("")
          parts.push(`Previous framed requirement: ${data.framed_question}`)
        }

        parts.push("")
        parts.push("Please review the context above and continue framing. You may ask clarifying questions or produce the framed requirement directly.")

        // Set the plan_id from the transcript so the pipeline links back
        setPlanId(null)
        setBasePlanId(transcriptPlanId)

        setPhase("framing")
        framer.startFraming(parts.join("\n"))
      } catch (err) {
        console.error("Failed to load transcript:", err)
      }
    },
    [framer]
  )

  // Watch for framer completion
  if (framer.status === "done" && framer.framedRequirement && phase === "framing") {
    setFramedRequirement(framer.framedRequirement)
    // Use the plan_id from the framer transcript (server-generated)
    // so the pipeline reuses the same ID for advisors + plan save.
    if (framer.planId && !planId) {
      setPlanId(framer.planId)
      setBasePlanId((prev) => prev || framer.planId)
    }
    setPhase("reviewing")
  }

  const handleProceed = useCallback(() => {
    setPhase("scanning")
  }, [])

  const handleCorrect = useCallback(
    (correction: string) => {
      setIsReframing(true)

      // Build context-rich prompt so the framer extends rather than restarts
      const parts: string[] = []
      parts.push(`Original request: ${rawDescription}`)

      // Include the framing conversation history
      if (framer.messages.length > 0) {
        parts.push("")
        parts.push("=== Previous Framing Conversation ===")
        for (const msg of framer.messages) {
          const role = msg.role === "framer" ? "Framer" : "User"
          parts.push(`${role}: ${msg.text}`)
        }
        parts.push("=== End Conversation ===")
      }

      // Include the current framed requirement
      if (framedRequirement) {
        parts.push("")
        parts.push("=== Current Framed Requirement ===")
        parts.push(`Type: ${framedRequirement.type}`)
        parts.push(`Title: ${framedRequirement.title}`)
        parts.push(`Description: ${framedRequirement.description}`)
        if (framedRequirement.acceptance_criteria?.length) {
          parts.push(`Acceptance Criteria:\n${framedRequirement.acceptance_criteria.map((ac: string) => `- ${ac}`).join("\n")}`)
        }
        if (framedRequirement.assumptions?.length) {
          parts.push(`Assumptions:\n${framedRequirement.assumptions.map((a: string) => `- ${a}`).join("\n")}`)
        }
        if (framedRequirement.out_of_scope?.length) {
          parts.push(`Out of Scope:\n${framedRequirement.out_of_scope.map((o: string) => `- ${o}`).join("\n")}`)
        }
        if (framedRequirement.stories?.length) {
          parts.push(`Stories (${framedRequirement.stories.length}):`)
          for (const story of framedRequirement.stories) {
            parts.push(`  - [${story.type}] ${story.title}: ${story.description}`)
          }
        }
        parts.push("=== End Current Requirement ===")
      }

      parts.push("")
      parts.push(`USER CORRECTION: ${correction}`)
      parts.push("")
      parts.push("Please revise the requirement based on the correction above. Keep everything that is still valid and only modify what the user asked to change. You may ask clarifying questions or produce the updated framed requirement directly.")

      framer.startFraming(parts.join("\n"))
      setPhase("framing")
      setIsReframing(false)
    },
    [rawDescription, framer, framedRequirement]
  )

  const startAdvisors = useCallback(
    (ctx: ProjectContext | null) => {
      if (!framedRequirement) return

      // If planId is already set (e.g. from re-advise init), reuse it.
      // Otherwise generate a fresh hex-only ID for a brand-new session.
      let usePlanId = planId
      if (!usePlanId) {
        usePlanId =
          crypto.randomUUID?.().replace(/-/g, "").slice(0, 12) ||
          Math.random().toString(36).slice(2, 14)
        setPlanId(usePlanId)
        setBasePlanId(usePlanId)
        setReviewVersion(1)
      }

      setPhase("advising")
      council.startCouncil(usePlanId, rawDescription, framedRequirement, ctx, basePlanId)
    },
    [framedRequirement, rawDescription, council, planId, basePlanId]
  )

  const handleScanSkip = useCallback(() => {
    setProjectContext(null)
    startAdvisors(null)
  }, [startAdvisors])

  const handleScanComplete = useCallback(() => {
    if (scanner.projectContext) {
      setProjectContext(scanner.projectContext)
      startAdvisors(scanner.projectContext)
    }
  }, [scanner.projectContext, startAdvisors])

  // Watch for scan completion
  if (scanner.phase === "done" && phase === "scanning") {
    handleScanComplete()
  }

  // Watch for council completion (from initial run or re-advise)
  if (council.session.stage === "completed" && phase === "advising") {
    setPhase("done")
    setSidebarRefreshKey((k) => k + 1)
  }

  // ---------------------------------------------------------------------------
  // Review actions: re-advise and re-frame from the plan view
  // ---------------------------------------------------------------------------

  const handleReAdvise = useCallback(
    async (feedback: string) => {
      if (!basePlanId) return
      setReAdviseError(null)

      try {
        // 1. Init review session on server (creates transcript with
        //    status="review", base_plan_id, and copies framer context).
        const res = await fetch("/api/council/review/init", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            base_plan_id: basePlanId,
            change_description: rawDescription,
            feedback,
          }),
        })

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}))
          throw new Error(errData.detail || `HTTP ${res.status}`)
        }

        const {
          plan_id: newPlanId,
          base_plan_id: basePId,
          framed_question: framedQuestion,
          framed_requirement: prevFramedReq,
        } = await res.json()

        // 2. Set up state for the new review pipeline.
        //    Use the server-generated plan_id so the eventual plan
        //    is linked back via base_plan_id.
        setPlanId(newPlanId)
        setBasePlanId(basePId)
        setFramedRequirement(null)

        // 3. Build a context-rich question for the framer including
        //    the full structured requirement from the previous plan
        //    so the framer has all context to revise from.
        const parts: string[] = []
        parts.push(`Original request: ${rawDescription}`)

        if (prevFramedReq) {
          parts.push("")
          parts.push("=== Previous Framed Requirement ===")
          parts.push(`Type: ${prevFramedReq.type}`)
          parts.push(`Title: ${prevFramedReq.title}`)
          parts.push(`Description: ${prevFramedReq.description}`)
          if (prevFramedReq.acceptance_criteria?.length) {
            parts.push(`Acceptance Criteria:\n${prevFramedReq.acceptance_criteria.map((ac: string) => `- ${ac}`).join("\n")}`)
          }
          if (prevFramedReq.assumptions?.length) {
            parts.push(`Assumptions:\n${prevFramedReq.assumptions.map((a: string) => `- ${a}`).join("\n")}`)
          }
          if (prevFramedReq.out_of_scope?.length) {
            parts.push(`Out of Scope:\n${prevFramedReq.out_of_scope.map((o: string) => `- ${o}`).join("\n")}`)
          }
          if (prevFramedReq.stories?.length) {
            parts.push(`Stories (${prevFramedReq.stories.length}):`)
            for (const story of prevFramedReq.stories) {
              parts.push(`  - [${story.type}] ${story.title}: ${story.description}`)
            }
          }
          parts.push("=== End Previous Requirement ===")
        } else if (framedQuestion) {
          parts.push("")
          parts.push(`Previous framed question: ${framedQuestion}`)
        }

        parts.push("")
        parts.push(`USER FEEDBACK FOR REVISION: ${feedback}`)
        parts.push("")
        parts.push("Please revise the requirement based on the feedback above. You may ask clarifying questions or produce the updated framed requirement directly.")

        const contextQuestion = parts.join("\n")

        // 4. Transition to framing phase -- the framer will review
        //    and potentially ask new questions before proceeding.
        setPhase("framing")
        framer.startFraming(contextQuestion)
      } catch (err) {
        // If init fails, stay on the current plan view and show error.
        setReAdviseError(
          err instanceof Error ? err.message : "Re-advise failed"
        )
      }
    },
    [basePlanId, rawDescription, framer]
  )

  const handleReFrame = useCallback(() => {
    // Build context-rich prompt so the framer extends rather than restarts
    const parts: string[] = []
    parts.push(`Original request: ${rawDescription}`)

    // Include the current framed requirement so the LLM has full context
    if (framedRequirement) {
      parts.push("")
      parts.push("=== Current Framed Requirement ===")
      parts.push(`Type: ${framedRequirement.type}`)
      parts.push(`Title: ${framedRequirement.title}`)
      parts.push(`Description: ${framedRequirement.description}`)
      if (framedRequirement.acceptance_criteria?.length) {
        parts.push(`Acceptance Criteria:\n${framedRequirement.acceptance_criteria.map((ac: string) => `- ${ac}`).join("\n")}`)
      }
      if (framedRequirement.assumptions?.length) {
        parts.push(`Assumptions:\n${framedRequirement.assumptions.map((a: string) => `- ${a}`).join("\n")}`)
      }
      if (framedRequirement.out_of_scope?.length) {
        parts.push(`Out of Scope:\n${framedRequirement.out_of_scope.map((o: string) => `- ${o}`).join("\n")}`)
      }
      if (framedRequirement.stories?.length) {
        parts.push(`Stories (${framedRequirement.stories.length}):`)
        for (const story of framedRequirement.stories) {
          parts.push(`  - [${story.type}] ${story.title}: ${story.description}`)
        }
      }
      parts.push("=== End Current Requirement ===")
    }

    parts.push("")
    parts.push("The user wants to re-frame this requirement. Please review the above context and revise. You may ask clarifying questions or produce an updated framed requirement directly.")

    setPhase("framing")
    framer.startFraming(parts.join("\n"))
  }, [rawDescription, framer, framedRequirement])

  // ---------------------------------------------------------------------------
  // Council review: all advisors review the plan, Business+Architect decide
  // ---------------------------------------------------------------------------

  const handleCouncilReview = useCallback(() => {
    if (!council.session.plan || !planId) return
    councilFeedback.requestFeedback(planId, council.session.plan)
  }, [council.session.plan, planId, councilFeedback])

  const handleApplyCouncilChanges = useCallback(
    async (acceptedChanges: string[]) => {
      if (!planId || !framedRequirement) return
      const newPlan = await councilFeedback.applyChanges(
        planId,
        rawDescription,
        framedRequirement,
        acceptedChanges,
        projectContext,
        basePlanId,
      )
      if (newPlan) {
        // Replace the current plan with the council-reviewed one
        council.loadFromPlan(newPlan)
        councilFeedback.reset()
        setSidebarRefreshKey((k) => k + 1)
      }
    },
    [planId, rawDescription, framedRequirement, projectContext, basePlanId, councilFeedback, council]
  )

  const handleDismissCouncilReview = useCallback(() => {
    councilFeedback.reset()
  }, [councilFeedback])

  // ---------------------------------------------------------------------------
  // Navigation: return to session vs new session
  // ---------------------------------------------------------------------------

  const handleNewSession = useCallback(() => {
    setPhase("input")
    setRawDescription("")
    setFramedRequirement(null)
    setProjectContext(null)
    setPlanId(null)
    setBasePlanId(null)
    setReviewVersion(1)
    setIsReframing(false)
    setReAdviseError(null)
    council.reset()
    councilFeedback.reset()
    scanner.reset()
    route.navigate("/")
  }, [council, councilFeedback, scanner, route])

  // ---------------------------------------------------------------------------
  // Load a plan from history into the current session
  // ---------------------------------------------------------------------------

  const handleLoadPlan = useCallback(
    (plan: ChangePlan, description: string, framedReq?: FramedRequirement) => {
      // Hydrate session state from a saved plan
      setRawDescription(description || plan.change_description)
      setPlanId(plan.plan_id)
      setBasePlanId(plan.plan_id)   // enables re-advise from history
      setReviewVersion(1)

      // Restore framed requirement so re-advise has the context it needs
      if (framedReq) {
        setFramedRequirement(framedReq)
      }

      // If the plan has advisor responses, show the completed plan
      council.loadFromPlan(plan)
      setPhase("done")
      route.navigate("/")
    },
    [council, route]
  )

  // ---------------------------------------------------------------------------
  // Sidebar: click a plan to load it into the session
  // ---------------------------------------------------------------------------

  const handleSidebarSelectPlan = useCallback(
    async (selectedPlanId: string) => {
      try {
        const res = await fetch(`/api/plans/${selectedPlanId}`)
        if (!res.ok) return
        const data = await res.json()

        const planData = data.plan as ChangePlan
        if (!planData) return

        planData.plan_id = planData.plan_id || data.plan_id || selectedPlanId
        planData.change_description =
          planData.change_description || data.change_description || ""
        if (!planData.base_plan_id && data.base_plan_id) {
          planData.base_plan_id = data.base_plan_id
        }
        if (
          (!planData.raw_advisor_responses ||
            Object.keys(planData.raw_advisor_responses).length === 0) &&
          data.advisor_responses
        ) {
          planData.raw_advisor_responses = data.advisor_responses
        }

        const framedReq = data.framed_requirement as FramedRequirement | undefined
        handleLoadPlan(planData, data.change_description || "", framedReq)
      } catch (err) {
        console.error("Failed to load plan from sidebar:", err)
      }
    },
    [handleLoadPlan]
  )

  // ---------------------------------------------------------------------------
  // Map session stage to pipeline tracker stage
  // ---------------------------------------------------------------------------

  function currentPipelineStage() {
    switch (phase) {
      case "framing":
        return "framing" as const
      case "reviewing":
        return "confirming" as const
      case "scanning":
        return "scanning" as const
      case "advising":
        if (council.session.stage === "synthesizing") return "synthesizing" as const
        if (council.session.stage === "completed") return "completed" as const
        if (council.session.stage === "error") return "error" as const
        return "advising" as const
      case "done":
        return "completed" as const
      default:
        return "idle" as const
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isHistoryView = route.view === "history"

  return (
    <>
      {/* Header with inline pipeline tracker */}
      <header className="flex items-center justify-between px-4 py-2.5 border-b border-border gap-4">
        <button
          onClick={handleNewSession}
          className="text-sm font-semibold text-text-primary hover:text-accent
                     transition-colors shrink-0"
        >
          Code Council
        </button>

        {/* Pipeline tracker -- race track, same width as content panels */}
        {!isHistoryView && phase !== "input" && (
          <div className="flex-1 min-w-0 flex justify-center">
            <div className="w-full max-w-4xl px-6">
              <PipelineTracker
                currentStage={currentPipelineStage()}
                advisorsDone={council.session.advisorResponses.length}
                advisorsTotal={council.session.advisorNames.length || 6}
              />
            </div>
          </div>
        )}

        <nav className="flex gap-4 shrink-0">
          {hasActiveSession && isHistoryView && (
            <button
              onClick={() => route.navigate("/")}
              className="text-xs text-accent hover:text-accent/80 transition-colors"
            >
              Current Session
            </button>
          )}
          <button
            onClick={handleNewSession}
            className="text-xs text-text-muted hover:text-text-secondary transition-colors"
          >
            New Session
          </button>
          <button
            onClick={() => route.navigate("/history")}
            className={`text-xs transition-colors ${
              isHistoryView
                ? "text-accent"
                : "text-text-muted hover:text-text-secondary"
            }`}
          >
            History
          </button>
        </nav>
      </header>

      {/* Body: sidebar + main content */}
      <div className="flex flex-1 min-h-0">
        {/* Plans sidebar -- always visible */}
        <PlanSidebar
          activePlanId={planId}
          onSelectPlan={handleSidebarSelectPlan}
          refreshKey={sidebarRefreshKey}
        />

        {/* Main content area */}
        <main className="flex-1 min-w-0 overflow-y-auto">
          {isHistoryView ? (
            <PlanHistory
              onLoadPlan={handleLoadPlan}
            />
          ) : (
            <>
              {/* Phase: Input */}
              {phase === "input" && (
                <DescriptionInput onSubmit={handleDescriptionSubmit} onLoadTranscript={handleLoadTranscript} />
              )}

              {/* Phase: Framing */}
              {phase === "framing" && (
                <FramerWizard
                  messages={framer.messages}
                  status={framer.status}
                  error={framer.error}
                  onReply={framer.sendReply}
                  onSkip={framer.skipFraming}
                />
              )}

              {/* Phase: Reviewing framed requirement */}
              {phase === "reviewing" && framedRequirement && (
                <RequirementReview
                  requirement={framedRequirement}
                  onProceed={handleProceed}
                  onCorrect={handleCorrect}
                  isReframing={isReframing}
                />
              )}

              {/* Phase: Project scanning */}
              {phase === "scanning" && (
                <ProjectScanner
                  isScanning={scanner.phase === "approving"}
                  error={scanner.error}
                  onUploadContext={scanner.uploadContext}
                  onSkip={handleScanSkip}
                  changeDescription={rawDescription}
                  framedRequirement={framedRequirement}
                />
              )}

              {/* Phase: Advisors running */}
              {phase === "advising" && (
                <>
                  <AdvisorsPanel
                    advisorNames={council.session.advisorNames}
                    advisorResponses={council.session.advisorResponses}
                    isComplete={
                      council.session.stage === "synthesizing" ||
                      council.session.stage === "completed"
                    }
                  />

                  {/* Synthesizing indicator moved to sticky footer */}

                  {council.session.stage === "error" && (
                    <ErrorDisplay
                      message={council.session.error || "An error occurred during advising"}
                      onRetry={() => startAdvisors(projectContext)}
                      onDismiss={handleNewSession}
                    />
                  )}
                </>
              )}

              {/* Phase: Plan complete */}
              {phase === "done" && reAdviseError && (
                <div className="max-w-6xl mx-auto w-full px-6 pt-4">
                  <ErrorDisplay
                    message={reAdviseError}
                    compact
                    onRetry={() => setReAdviseError(null)}
                    onDismiss={() => setReAdviseError(null)}
                  />
                </div>
              )}
              {phase === "done" && council.session.plan && (
                <PlanView
                  plan={council.session.plan}
                  duration={council.session.duration}
                  onReAdvise={handleReAdvise}
                  onReFrame={handleReFrame}
                  isReviewing={council.isRunning}
                  onCouncilReview={handleCouncilReview}
                  councilFeedback={councilFeedback.state}
                  isCouncilReviewing={councilFeedback.isRunning}
                  onApplyCouncilChanges={handleApplyCouncilChanges}
                  onDismissCouncilReview={handleDismissCouncilReview}
                  isApplyingCouncilChanges={councilFeedback.isApplying}
                />
              )}
            </>
          )}
        </main>
      </div>

      {/* Sticky status footer -- shown during active operations */}
      {(() => {
        let statusText = ""
        let colorClass = ""

        if (councilFeedback.isApplying) {
          statusText = "Applying changes & re-planning..."
          colorClass = "text-purple-600 dark:text-purple-400 border-purple-500/20 bg-purple-500/5"
        } else if (councilFeedback.state.stage === "deciding") {
          statusText = "Business & Architect deciding..."
          colorClass = "text-amber-600 dark:text-amber-400 border-amber-500/20 bg-amber-500/5"
        } else if (councilFeedback.state.stage === "reviewing") {
          statusText = "Advisors reviewing plan..."
          colorClass = "text-accent border-accent/20 bg-accent/5"
        } else if (phase === "done" && council.isRunning) {
          statusText = "Re-advising -- new plan incoming"
          colorClass = "text-amber-600 dark:text-amber-400 border-amber-500/20 bg-amber-500/5"
        } else if (council.session.stage === "synthesizing") {
          statusText = "Synthesizing plan..."
          colorClass = "text-text-muted border-border bg-surface-secondary"
        }

        if (!statusText) return null

        return (
          <div className={`sticky bottom-0 z-10 border-t px-4 py-2.5 flex items-center
                           justify-center gap-2 backdrop-blur-sm ${colorClass}`}>
            <span className="flex items-center gap-1">
              <span className="animate-pulse-dot">.</span>
              <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
              <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
            </span>
            <span className="text-sm font-medium">{statusText}</span>
          </div>
        )
      })()}
    </>
  )
}
