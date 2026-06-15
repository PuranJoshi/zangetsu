import { useState } from "react"
import type { CouncilFeedbackState, RecommendationDecision } from "../types"
import { ADVISOR_CONFIG } from "../types"
import { MarkdownContent } from "./MarkdownContent"

interface Props {
  feedback: CouncilFeedbackState
  /** Called when the user applies their selected changes. */
  onApply?: (acceptedChanges: string[]) => void
  /** Called when the user dismisses the council review. */
  onDismiss?: () => void
  /** Whether the apply action is in progress. */
  isApplying?: boolean
}

const DECISION_OPTIONS = ["ACCEPT", "DEFER", "DROP"] as const
type DecisionValue = (typeof DECISION_OPTIONS)[number]

function DecisionBadge({
  decision,
  editable,
  onChange,
}: {
  decision: string
  editable?: boolean
  onChange?: (value: DecisionValue) => void
}) {
  const styles: Record<string, string> = {
    ACCEPT: "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20",
    DEFER: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
    DROP: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20",
  }

  if (editable && onChange) {
    return (
      <select
        value={decision}
        onChange={(e) => onChange(e.target.value as DecisionValue)}
        className={`px-2 py-0.5 text-[10px] font-semibold uppercase rounded border
                    cursor-pointer appearance-none text-center
                    focus:outline-none focus:ring-1 focus:ring-accent
                    ${styles[decision] || "bg-surface-tertiary text-text-muted border-border"}`}
      >
        {DECISION_OPTIONS.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    )
  }

  return (
    <span
      className={`px-2 py-0.5 text-[10px] font-semibold uppercase rounded border ${
        styles[decision] || "bg-surface-tertiary text-text-muted border-border"
      }`}
    >
      {decision}
    </span>
  )
}

function PriorityBadge({ priority }: { priority: string }) {
  const styles: Record<string, string> = {
    HIGH: "bg-red-500/10 text-red-600 dark:text-red-400",
    MEDIUM: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
    LOW: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  }
  return (
    <span
      className={`px-1.5 py-0.5 text-[9px] font-semibold uppercase rounded ${
        styles[priority] || "bg-surface-tertiary text-text-muted"
      }`}
    >
      {priority}
    </span>
  )
}

function VerdictBanner({
  verdict,
  rationale,
}: {
  verdict: string
  rationale: string
}) {
  const isProceed = verdict === "PROCEED"
  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-lg border ${
        isProceed
          ? "bg-green-500/5 border-green-500/20"
          : "bg-amber-500/5 border-amber-500/20"
      }`}
    >
      <span className="text-lg mt-0.5">
        {isProceed ? "\u2705" : "\uD83D\uDD04"}
      </span>
      <div className="flex-1 min-w-0">
        <span
          className={`text-sm font-semibold ${
            isProceed
              ? "text-green-600 dark:text-green-400"
              : "text-amber-600 dark:text-amber-400"
          }`}
        >
          {isProceed ? "PROCEED" : "REVISE"}
        </span>
        <p className="text-sm text-text-secondary mt-1 leading-relaxed">
          {rationale}
        </p>
      </div>
    </div>
  )
}

function DecisionCard({
  rec,
  editable,
  currentDecision,
  onDecisionChange,
}: {
  rec: RecommendationDecision
  editable?: boolean
  currentDecision: DecisionValue
  onDecisionChange?: (value: DecisionValue) => void
}) {
  const config = ADVISOR_CONFIG[rec.advisor]
  return (
    <div className="flex flex-col gap-2 px-4 py-3 border border-border rounded-lg">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          {config && (
            <span className="text-xs" style={{ color: config.color }}>
              {config.icon}
            </span>
          )}
          <span className="text-xs font-medium text-text-secondary">
            {rec.advisor}
          </span>
          <PriorityBadge priority={rec.priority} />
        </div>
        <DecisionBadge
          decision={currentDecision}
          editable={editable}
          onChange={onDecisionChange}
        />
      </div>
      <p className="text-sm text-text-primary leading-relaxed">
        {rec.recommendation}
      </p>
      <p className="text-xs text-text-muted italic">{rec.reason}</p>
    </div>
  )
}

export function CouncilReviewPanel({
  feedback,
  onApply,
  onDismiss,
  isApplying,
}: Props) {
  const { stage, advisorReviews, decision } = feedback

  // Track user overrides for each recommendation decision.
  // Initialised from the decision gate's suggestions when available.
  const [overrides, setOverrides] = useState<Record<number, DecisionValue>>({})

  // Derive the current decision for each recommendation
  function currentDecision(index: number): DecisionValue {
    if (overrides[index] !== undefined) return overrides[index]
    if (decision?.decisions[index]) return decision.decisions[index].decision as DecisionValue
    return "DROP"
  }

  function handleDecisionChange(index: number, value: DecisionValue) {
    setOverrides((prev) => ({ ...prev, [index]: value }))
  }

  function handleApply() {
    if (!decision || !onApply) return
    const accepted = decision.decisions
      .filter((_, i) => currentDecision(i) === "ACCEPT")
      .map((rec) => rec.recommendation)
    onApply(accepted)
  }

  const hasDecisions = decision && decision.decisions.length > 0
  const acceptedCount = hasDecisions
    ? decision.decisions.filter((_, i) => currentDecision(i) === "ACCEPT").length
    : 0
  const isEditable = stage === "completed" && !isApplying

  return (
    <div className="flex flex-col gap-4 animate-card-enter">
      {/* Header */}
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Council Review
        </h3>
        {/* Status indicators moved to sticky footer in App.tsx */}
      </div>

      {/* Advisor reviews as they stream in */}
      {advisorReviews.length > 0 && (
        <div className="border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-2.5 bg-surface-secondary border-b border-border">
            <span className="text-xs font-medium text-text-secondary">
              Advisor Reviews ({advisorReviews.length})
            </span>
          </div>
          <div className="divide-y divide-border">
            {advisorReviews.map((ar) => {
              const config = ADVISOR_CONFIG[ar.name]
              const isProceed = ar.review.trim().toUpperCase() === "PROCEED"
              return (
                <div key={ar.name} className="px-4 py-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    {config && (
                      <span className="text-xs" style={{ color: config.color }}>
                        {config.icon}
                      </span>
                    )}
                    <span className="text-xs font-medium text-text-primary">
                      {ar.name}
                    </span>
                    {isProceed && (
                      <span
                        className="px-1.5 py-0.5 text-[9px] font-semibold uppercase rounded
                                       bg-green-500/10 text-green-600 dark:text-green-400"
                      >
                        PROCEED
                      </span>
                    )}
                  </div>
                  {!isProceed && (
                    <div className="text-sm text-text-secondary">
                      <MarkdownContent content={ar.review} />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Decision gate result with editable overrides */}
      {decision && (
        <div className="flex flex-col gap-3">
          <VerdictBanner verdict={decision.verdict} rationale={decision.rationale} />

          {hasDecisions && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
                  Recommendations ({acceptedCount} accepted,{" "}
                  {decision.decisions.filter((_, i) => currentDecision(i) === "DEFER").length}{" "}
                  deferred,{" "}
                  {decision.decisions.filter((_, i) => currentDecision(i) === "DROP").length}{" "}
                  dropped)
                </span>
                {isEditable && (
                  <span className="text-[10px] text-text-muted">
                    Change decisions with the dropdowns
                  </span>
                )}
              </div>
              {decision.decisions.map((rec, i) => (
                <DecisionCard
                  key={i}
                  rec={rec}
                  editable={isEditable}
                  currentDecision={currentDecision(i)}
                  onDecisionChange={(val) => handleDecisionChange(i, val)}
                />
              ))}
            </div>
          )}

          {decision.accepted_changes_summary && decision.verdict === "REVISE" && (
            <div className="border border-border rounded-lg px-4 py-3">
              <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
                Accepted Changes
              </span>
              <div className="mt-2 text-sm text-text-secondary">
                <MarkdownContent content={decision.accepted_changes_summary} />
              </div>
            </div>
          )}

          {/* Action buttons */}
          {isEditable && onApply && (
            <div className="flex items-center gap-2 pt-2 border-t border-border">
              {acceptedCount > 0 && (
                <button
                  onClick={handleApply}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                             bg-purple-500/10 text-purple-600 dark:text-purple-400
                             border border-purple-500/30
                             hover:bg-purple-500/20 transition-colors"
                >
                  Apply {acceptedCount} change{acceptedCount !== 1 ? "s" : ""} & re-plan
                </button>
              )}
              {onDismiss && (
                <button
                  onClick={onDismiss}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                             text-text-muted hover:text-text-secondary
                             transition-colors"
                >
                  Dismiss
                </button>
              )}
              {acceptedCount === 0 && !onDismiss && (
                <span className="text-xs text-text-muted">
                  No changes accepted. Use dropdowns above to accept recommendations.
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {stage === "error" && feedback.error && (
        <div className="px-4 py-3 rounded-lg bg-red-500/5 border border-red-500/20">
          <span className="text-sm text-red-600 dark:text-red-400">
            {feedback.error}
          </span>
        </div>
      )}
    </div>
  )
}
