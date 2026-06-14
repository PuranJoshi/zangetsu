import { useState } from "react"
import type { FramedRequirement } from "../types"

interface Props {
  requirement: FramedRequirement
  onProceed: () => void
  onCorrect: (correction: string) => void
  isReframing: boolean
}

function StoryCard({ story, depth = 0 }: { story: FramedRequirement; depth?: number }) {
  const [expanded, setExpanded] = useState(depth === 0)

  return (
    <div
      className="border border-border rounded-lg overflow-hidden"
      style={{ marginLeft: depth > 0 ? "1rem" : 0 }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3
                   bg-surface-secondary hover:bg-surface-tertiary
                   transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono px-2 py-0.5 rounded
                           bg-accent/10 text-accent uppercase">
            {story.type}
          </span>
          <span className="text-sm font-medium text-text-primary">
            {story.title}
          </span>
        </div>
        <span className="text-text-muted text-xs">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>

      {expanded && (
        <div className="px-4 py-3 space-y-3 text-sm">
          <p className="text-text-secondary">{story.description}</p>

          {story.acceptance_criteria.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-1">
                Acceptance Criteria
              </h4>
              <ul className="space-y-1">
                {story.acceptance_criteria.map((ac, i) => (
                  <li key={i} className="flex items-start gap-2 text-text-secondary">
                    <span className="text-accent mt-0.5 text-xs">{"\u2713"}</span>
                    <span>{ac}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Nested stories */}
          {story.stories.length > 0 && (
            <div className="space-y-2 mt-2">
              {story.stories.map((sub, i) => (
                <StoryCard key={i} story={sub} depth={depth + 1} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function RequirementReview({
  requirement,
  onProceed,
  onCorrect,
  isReframing,
}: Props) {
  const [showCorrection, setShowCorrection] = useState(false)
  const [correctionText, setCorrectionText] = useState("")

  const handleCorrect = () => {
    const trimmed = correctionText.trim()
    if (!trimmed) return
    setCorrectionText("")
    setShowCorrection(false)
    onCorrect(trimmed)
  }

  return (
    <div className="flex flex-col gap-5 py-6 px-4 max-w-2xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-mono px-2 py-1 rounded
                         bg-accent/10 text-accent uppercase font-semibold">
          {requirement.type}
        </span>
        <h2 className="text-xl font-semibold text-text-primary">
          {requirement.title}
        </h2>
      </div>

      {/* Description */}
      <p className="text-sm text-text-secondary leading-relaxed">
        {requirement.description}
      </p>

      {/* Acceptance criteria */}
      {requirement.acceptance_criteria.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
            Acceptance Criteria
          </h3>
          <ul className="space-y-1.5">
            {requirement.acceptance_criteria.map((ac, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                <span className="text-accent mt-0.5">{"\u2713"}</span>
                <span>{ac}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Assumptions */}
      {requirement.assumptions.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
            Assumptions
          </h3>
          <ul className="list-disc list-inside text-sm text-text-secondary space-y-1">
            {requirement.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Out of scope */}
      {requirement.out_of_scope.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
            Out of Scope
          </h3>
          <ul className="list-disc list-inside text-sm text-text-secondary space-y-1">
            {requirement.out_of_scope.map((o, i) => (
              <li key={i}>{o}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Stories */}
      {requirement.stories.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
            Stories ({requirement.stories.length})
          </h3>
          <div className="space-y-2">
            {requirement.stories.map((story, i) => (
              <StoryCard key={i} story={story} />
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-col gap-3 mt-2 pt-4 border-t border-border">
        {isReframing ? (
          <div className="flex items-center gap-2 text-sm text-text-muted">
            <span className="animate-pulse-dot">.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
            <span className="ml-1">Re-framing with your corrections...</span>
          </div>
        ) : (
          <>
            <div className="flex gap-3">
              <button
                onClick={onProceed}
                className="px-5 py-2 rounded-lg text-sm font-medium
                           bg-accent text-white hover:opacity-90 transition-opacity"
              >
                Proceed to advisors
              </button>
              <button
                onClick={() => setShowCorrection(!showCorrection)}
                className="px-5 py-2 rounded-lg text-sm font-medium
                           border border-border text-text-secondary
                           hover:border-text-muted hover:text-text-primary
                           transition-colors"
              >
                Let me correct
              </button>
            </div>

            {showCorrection && (
              <div className="flex gap-2">
                <input
                  type="text"
                  value={correctionText}
                  onChange={(e) => setCorrectionText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleCorrect()
                  }}
                  placeholder="What needs to change?"
                  className="flex-1 px-3 py-2 rounded-lg border border-border
                             bg-surface text-sm text-text-primary
                             placeholder:text-text-muted
                             focus:outline-none focus:ring-2 focus:ring-accent/40"
                  autoFocus
                />
                <button
                  onClick={handleCorrect}
                  disabled={!correctionText.trim()}
                  className="px-4 py-2 rounded-lg text-sm bg-accent text-white
                             hover:opacity-90 disabled:opacity-40
                             disabled:cursor-not-allowed transition-opacity"
                >
                  Re-frame
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
