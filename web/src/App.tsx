import { useState, useCallback, useRef } from "react"
import type { FramedRequirement, ProjectContext, ChangePlan } from "./types"
import { useFramer } from "./hooks/useFramer"
import { useCouncilStream } from "./hooks/useCouncilStream"
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
  const [reviewVersion, setReviewVersion] = useState(1)
  const [isReframing, setIsReframing] = useState(false)

  // Track whether the user has an active session (not idle input)
  const hasActiveSession = phase !== "input"

  // Hooks
  const framer = useFramer()
  const council = useCouncilStream()
  const scanner = useProjectScan()

  // Guard against duplicate phase transitions during a single render
  const phaseRef = useRef(phase)
  phaseRef.current = phase

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

  // Watch for framer completion
  if (framer.status === "done" && framer.framedRequirement && phase === "framing") {
    setFramedRequirement(framer.framedRequirement)
    setPhase("reviewing")
  }

  const handleProceed = useCallback(() => {
    setPhase("scanning")
  }, [])

  const handleCorrect = useCallback(
    (correction: string) => {
      setIsReframing(true)
      const correctedDescription = `${rawDescription}\n\nCorrection: ${correction}`
      framer.startFraming(correctedDescription)
      setPhase("framing")
      setIsReframing(false)
    },
    [rawDescription, framer]
  )

  const handleScanSkip = useCallback(() => {
    setProjectContext(null)
    startAdvisors(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleScanComplete = useCallback(() => {
    if (scanner.projectContext) {
      setProjectContext(scanner.projectContext)
      startAdvisors(scanner.projectContext)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanner.projectContext])

  // Watch for scan completion
  if (scanner.phase === "done" && phase === "scanning") {
    handleScanComplete()
  }

  const startAdvisors = useCallback(
    (ctx: ProjectContext | null) => {
      if (!framedRequirement) return

      const id =
        crypto.randomUUID?.().replace(/-/g, "").slice(0, 12) ||
        Math.random().toString(36).slice(2, 14)
      const slug = rawDescription
        .replace(/[^a-zA-Z0-9\s]/g, "")
        .trim()
        .toLowerCase()
        .split(/\s+/)
        .slice(0, 4)
        .join("-") || "plan"
      const fullPlanId = `${id}-${slug}`

      setPlanId(fullPlanId)
      setBasePlanId(fullPlanId)
      setReviewVersion(1)
      setPhase("advising")

      council.startCouncil(fullPlanId, rawDescription, framedRequirement, ctx)
    },
    [framedRequirement, rawDescription, council]
  )

  // Watch for council completion (from initial run or re-advise)
  if (council.session.stage === "completed" && phase === "advising") {
    setPhase("done")
  }

  // ---------------------------------------------------------------------------
  // Review actions: re-advise and re-frame from the plan view
  // ---------------------------------------------------------------------------

  const handleReAdvise = useCallback(
    async (feedback: string) => {
      if (!basePlanId) return

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
        } = await res.json()

        // 2. Set up state for the new review pipeline.
        //    Use the server-generated plan_id so the eventual plan
        //    is linked back via base_plan_id.
        setPlanId(newPlanId)
        setBasePlanId(basePId)
        setFramedRequirement(null)

        // 3. Build a context-rich question for the framer:
        //    original framed question + re-advise feedback.
        const contextQuestion = framedQuestion
          ? `Previous requirement:\n${framedQuestion}\n\nFeedback for revision:\n${feedback}`
          : `${rawDescription}\n\nFeedback for revision:\n${feedback}`

        // 4. Transition to framing phase -- the framer will review
        //    and potentially ask new questions before proceeding.
        setPhase("framing")
        framer.startFraming(contextQuestion)
      } catch {
        // If init fails, stay on the current plan view.
      }
    },
    [basePlanId, rawDescription, framer]
  )

  const handleReFrame = useCallback(() => {
    // Go all the way back to the framing phase
    setPhase("framing")
    framer.startFraming(rawDescription)
  }, [rawDescription, framer])

  // ---------------------------------------------------------------------------
  // Navigation: return to session vs new session
  // ---------------------------------------------------------------------------

  const handleGoHome = useCallback(() => {
    // If there's an active session, just navigate back to it without resetting
    route.navigate("/")
  }, [route])

  const handleNewSession = useCallback(() => {
    setPhase("input")
    setRawDescription("")
    setFramedRequirement(null)
    setProjectContext(null)
    setPlanId(null)
    setBasePlanId(null)
    setReviewVersion(1)
    setIsReframing(false)
    council.reset()
    scanner.reset()
    route.navigate("/")
  }, [council, scanner, route])

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
  const historyPlanId = route.view === "history" ? route.planId : undefined

  return (
    <>
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-border">
        <button
          onClick={handleGoHome}
          className="text-sm font-semibold text-text-primary hover:text-accent
                     transition-colors"
        >
          Code Council
        </button>
        <nav className="flex gap-4">
          {hasActiveSession && isHistoryView && (
            <button
              onClick={handleGoHome}
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

      {/* Pipeline tracker (visible when in a session, not in history) */}
      {!isHistoryView && phase !== "input" && (
        <PipelineTracker
          currentStage={currentPipelineStage()}
          advisorsDone={council.session.advisorResponses.length}
          advisorsTotal={council.session.advisorNames.length || 6}
        />
      )}

      {/* Main content area */}
      <main className="flex-1">
        {isHistoryView ? (
          <PlanHistory
            planId={historyPlanId}
            onLoadPlan={handleLoadPlan}
          />
        ) : (
          <>
            {/* Phase: Input */}
            {phase === "input" && (
              <DescriptionInput onSubmit={handleDescriptionSubmit} />
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
                treeResult={scanner.treeResult}
                discoveredFiles={scanner.discoveredFiles}
                isScanning={
                  scanner.phase === "scanning" ||
                  scanner.phase === "discovering" ||
                  scanner.phase === "approving"
                }
                onScanPath={scanner.scanTree}
                onDiscover={scanner.discoverFiles}
                onApprove={scanner.approveFiles}
                onSkip={handleScanSkip}
                changeDescription={rawDescription}
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

                {council.session.stage === "synthesizing" && (
                  <div className="text-center py-4">
                    <span className="text-sm text-text-muted flex items-center justify-center gap-1">
                      <span className="animate-pulse-dot">.</span>
                      <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
                      <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
                      <span className="ml-1">Synthesizing plan...</span>
                    </span>
                  </div>
                )}

                {council.session.stage === "error" && (
                  <div className="mx-4 my-4 p-4 rounded-lg bg-red-500/10 border border-red-500/30">
                    <p className="text-sm text-red-600 dark:text-red-400">
                      {council.session.error || "An error occurred"}
                    </p>
                  </div>
                )}
              </>
            )}

            {/* Phase: Plan complete */}
            {phase === "done" && council.session.plan && (
              <PlanView
                plan={council.session.plan}
                duration={council.session.duration}
                onReAdvise={handleReAdvise}
                onReFrame={handleReFrame}
                isReviewing={council.isRunning}
              />
            )}
          </>
        )}
      </main>
    </>
  )
}
