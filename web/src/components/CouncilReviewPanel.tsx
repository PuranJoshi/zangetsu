import type { CouncilFeedbackState, RecommendationDecision } from "../types"
import { ADVISOR_CONFIG } from "../types"
import { MarkdownContent } from "./MarkdownContent"

interface Props {
  feedback: CouncilFeedbackState
}

function DecisionBadge({ decision }: { decision: string }) {
  const styles: Record<string, string> = {
    ACCEPT: "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20",
    DEFER: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20",
    DROP: "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20",
  }
  return (
    <span className={`px-2 py-0.5 text-[10px] font-semibold uppercase rounded border ${styles[decision] || "bg-surface-tertiary text-text-muted border-border"}`}>
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
    <span className={`px-1.5 py-0.5 text-[9px] font-semibold uppercase rounded ${styles[priority] || "bg-surface-tertiary text-text-muted"}`}>
      {priority}
    </span>
  )
}

function VerdictBanner({ verdict, rationale }: { verdict: string; rationale: string }) {
  const isProceed = verdict === "PROCEED"
  return (
    <div className={`flex items-start gap-3 px-4 py-3 rounded-lg border ${
      isProceed
        ? "bg-green-500/5 border-green-500/20"
        : "bg-amber-500/5 border-amber-500/20"
    }`}>
      <span className="text-lg mt-0.5">
        {isProceed ? "\u2705" : "\uD83D\uDD04"}
      </span>
      <div className="flex-1 min-w-0">
        <span className={`text-sm font-semibold ${
          isProceed
            ? "text-green-600 dark:text-green-400"
            : "text-amber-600 dark:text-amber-400"
        }`}>
          {isProceed ? "PROCEED" : "REVISE"}
        </span>
        <p className="text-sm text-text-secondary mt-1 leading-relaxed">
          {rationale}
        </p>
      </div>
    </div>
  )
}

function DecisionCard({ rec }: { rec: RecommendationDecision }) {
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
        <DecisionBadge decision={rec.decision} />
      </div>
      <p className="text-sm text-text-primary leading-relaxed">
        {rec.recommendation}
      </p>
      <p className="text-xs text-text-muted italic">
        {rec.reason}
      </p>
    </div>
  )
}

export function CouncilReviewPanel({ feedback }: Props) {
  const { stage, advisorReviews, decision } = feedback

  return (
    <div className="flex flex-col gap-4 animate-card-enter">
      {/* Header */}
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
          Council Review
        </h3>
        {stage === "reviewing" && (
          <span className="flex items-center gap-0.5 text-xs text-accent">
            <span className="animate-pulse-dot">.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
            <span className="ml-1">Advisors reviewing plan...</span>
          </span>
        )}
        {stage === "deciding" && (
          <span className="flex items-center gap-0.5 text-xs text-amber-600 dark:text-amber-400">
            <span className="animate-pulse-dot">.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
            <span className="ml-1">Business & Architect deciding...</span>
          </span>
        )}
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
                      <span className="px-1.5 py-0.5 text-[9px] font-semibold uppercase rounded
                                       bg-green-500/10 text-green-600 dark:text-green-400">
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

      {/* Decision gate result */}
      {decision && (
        <div className="flex flex-col gap-3">
          <VerdictBanner
            verdict={decision.verdict}
            rationale={decision.rationale}
          />

          {decision.decisions.length > 0 && (
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
                Recommendations ({decision.decisions.filter((d) => d.decision === "ACCEPT").length} accepted,{" "}
                {decision.decisions.filter((d) => d.decision === "DEFER").length} deferred,{" "}
                {decision.decisions.filter((d) => d.decision === "DROP").length} dropped)
              </span>
              {decision.decisions.map((rec, i) => (
                <DecisionCard key={i} rec={rec} />
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
