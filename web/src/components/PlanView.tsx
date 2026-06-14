import { useState } from "react"
import type { ChangePlan, ImplementationStep, IncrementalChange } from "../types"
import { MarkdownContent } from "./MarkdownContent"

interface Props {
  plan: ChangePlan
  duration: number | null
  /** Called when the user wants to re-run advisors with feedback. */
  onReAdvise?: (feedback: string) => void
  /** Called when the user wants to go back to framing. */
  onReFrame?: () => void
  /** Whether a review action is currently in progress. */
  isReviewing?: boolean
  /** History detail: navigate back to history list. */
  onBack?: () => void
  /** History detail: load this plan into an active session. */
  onLoadIntoSession?: () => void
}

// ── Collapsible panel ──────────────────────────────────────────────────────

function Panel({
  title,
  children,
  defaultOpen = false,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2.5
                   bg-surface-secondary hover:bg-surface-tertiary
                   transition-colors text-left"
      >
        <span className="text-sm font-medium text-text-primary">{title}</span>
        <span className="text-text-muted text-xs">{open ? "\u25B2" : "\u25BC"}</span>
      </button>
      {open && <div className="px-4 py-3">{children}</div>}
    </div>
  )
}

// ── Group heading ──────────────────────────────────────────────────────────

function GroupHeading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-wider text-text-muted">
      {children}
    </h3>
  )
}

// ── Advisor notes tabs ─────────────────────────────────────────────────────

function AdvisorNotesTabs({
  sections,
}: {
  sections: { key: string; title: string; content: string }[]
}) {
  const [activeKey, setActiveKey] = useState(sections[0]?.key ?? "")
  const active = sections.find((s) => s.key === activeKey) ?? sections[0]

  return (
    <div className="flex flex-col gap-3">
      <GroupHeading>Advisor Notes</GroupHeading>

      <div className="relative border border-border rounded-lg overflow-hidden min-h-[12rem]">
        {/* Tab bar -- in flow, sets the container height */}
        <div className="inline-flex flex-col w-40 min-h-[12rem] bg-surface-secondary border-r border-border">
          {sections.map((s) => (
            <button
              key={s.key}
              onClick={() => setActiveKey(s.key)}
              className={`px-4 py-2.5 text-xs font-medium text-left whitespace-nowrap
                          transition-colors border-l-2
                ${
                  s.key === activeKey
                    ? "border-accent text-accent bg-surface-primary"
                    : "border-transparent text-text-muted hover:text-text-secondary hover:bg-surface-tertiary"
                }`}
            >
              {s.title}
            </button>
          ))}
        </div>

        {/* Content -- absolutely positioned, clipped to tab bar height */}
        {active && (
          <div className="absolute top-0 bottom-0 left-40 right-0 px-5 py-4 scroll-on-hover">
            <MarkdownContent content={active.content} />
          </div>
        )}
      </div>
    </div>
  )
}

// ── Implementation tabs (stories + steps + files) ──────────────────────────

/** Build a tab entry for each incremental change, resolving its steps and files. */
function buildImplementationTabs(
  changes: IncrementalChange[],
  allSteps: ImplementationStep[],
  allFiles: string[],
) {
  const stepMap = new Map(allSteps.map((s) => [s.order, s]))
  const claimed = new Set<number>()
  const claimedFiles = new Set<string>()

  const tabs = changes.map((change, i) => {
    const steps = change.steps
      .map((n) => stepMap.get(n))
      .filter((s): s is ImplementationStep => !!s)
    change.steps.forEach((n) => claimed.add(n))

    // Collect unique file paths touched by this story's steps
    const files = [...new Set(steps.map((s) => s.file_path))]
    files.forEach((f) => claimedFiles.add(f))

    return { key: `change-${i}`, change, steps, files }
  })

  // Orphan steps not referenced by any incremental change
  const orphans = allSteps.filter((s) => !claimed.has(s.order))
  const orphanFiles = [...new Set(orphans.map((s) => s.file_path))]
  // Also include any plan-level affected files not claimed by any story
  const unclaimedPlanFiles = allFiles.filter((f) => !claimedFiles.has(f))
  const extraFiles = [...new Set([...orphanFiles, ...unclaimedPlanFiles])]

  return { tabs, orphans, extraFiles }
}

function ImplementationTabs({
  plan,
}: {
  plan: ChangePlan
}) {
  const changes = plan.incremental_changes ?? []
  const hasChanges = changes.length > 0
  const { tabs, orphans, extraFiles } = hasChanges
    ? buildImplementationTabs(changes, plan.implementation_steps, plan.affected_files)
    : {
        tabs: [] as ReturnType<typeof buildImplementationTabs>["tabs"],
        orphans: plan.implementation_steps,
        extraFiles: plan.affected_files,
      }

  // If no incremental changes, show a single "All Steps" tab
  const allTabs = [
    ...tabs,
    ...(orphans.length > 0
      ? [{
          key: "orphan",
          change: null as IncrementalChange | null,
          steps: orphans,
          files: extraFiles,
        }]
      : []),
  ]

  const [activeKey, setActiveKey] = useState(allTabs[0]?.key ?? "")
  const active = allTabs.find((t) => t.key === activeKey) ?? allTabs[0]

  return (
    <div className="flex flex-col gap-3">
      <GroupHeading>Implementation</GroupHeading>

      <div className="relative border border-border rounded-lg overflow-hidden min-h-[30rem]">
        {/* Tab bar -- in flow, sets the container height */}
        <div className="inline-flex flex-col w-48 min-h-[30rem] bg-surface-secondary border-r border-border">
          {allTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveKey(tab.key)}
              className={`px-3 py-2.5 text-left transition-colors border-l-2
                ${
                  tab.key === activeKey
                    ? "border-accent bg-surface-primary"
                    : "border-transparent hover:bg-surface-tertiary"
                }`}
            >
              {tab.change ? (
                <span className="flex items-center gap-1.5">
                  <span
                    className={`px-1 py-px text-[9px] font-semibold uppercase rounded tracking-wide shrink-0 ${
                      tab.change.type === "story"
                        ? "bg-blue-500/10 text-blue-600 dark:text-blue-400"
                        : tab.change.type === "bug"
                          ? "bg-red-500/10 text-red-600 dark:text-red-400"
                          : "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                    }`}
                  >
                    {tab.change.type}
                  </span>
                  <span className="text-xs font-medium text-text-primary truncate">
                    {tab.change.title}
                  </span>
                </span>
              ) : (
                <span className="text-xs font-medium text-text-primary">
                  Other Steps
                </span>
              )}
              <span className="block text-[10px] text-text-muted mt-0.5">
                {tab.steps.length} step{tab.steps.length !== 1 ? "s" : ""}
                {" \u00B7 "}
                {tab.files.length} file{tab.files.length !== 1 ? "s" : ""}
              </span>
            </button>
          ))}
        </div>

        {/* Content -- absolutely positioned, clipped to tab bar height */}
        <div className="absolute top-0 bottom-0 left-48 right-0 px-5 py-4 scroll-on-hover">
          {active ? (
            <div className="flex flex-col gap-4">
              {/* Story/task description + acceptance criteria */}
              {active.change && (
                <div className="flex flex-col gap-3 pb-3 border-b border-border">
                  <p className="text-sm text-text-secondary leading-relaxed">
                    {active.change.description}
                  </p>
                  {active.change.acceptance_criteria.length > 0 && (
                    <div>
                      <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
                        Acceptance Criteria
                      </span>
                      <ul className="mt-1.5 space-y-1">
                        {active.change.acceptance_criteria.map((ac, j) => (
                          <li key={j} className="flex items-start gap-2 text-sm text-text-secondary">
                            <span className="text-accent mt-0.5 shrink-0">{"\u2713"}</span>
                            <span>{ac}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Implementation steps */}
              <div>
                <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
                  Steps
                </span>
                <ul className="mt-2 space-y-3">
                  {active.steps.map((step) => (
                    <li key={step.order} className="flex items-start gap-3">
                      <span className="w-1.5 h-1.5 rounded-full bg-accent shrink-0 mt-2" />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                          <code className="text-xs font-mono text-text-secondary bg-surface-tertiary
                                           px-1.5 py-0.5 rounded truncate max-w-[300px]">
                            {step.file_path}
                          </code>
                          <span
                            className={`text-xs px-1.5 py-0.5 rounded ${
                              step.action === "create"
                                ? "bg-green-500/10 text-green-600 dark:text-green-400"
                                : step.action === "delete"
                                  ? "bg-red-500/10 text-red-600 dark:text-red-400"
                                  : "bg-blue-500/10 text-blue-600 dark:text-blue-400"
                            }`}
                          >
                            {step.action}
                          </span>
                        </div>
                        <p className="text-sm text-text-secondary leading-relaxed">
                          {step.description}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>

              {/* Affected files for this story */}
              {active.files.length > 0 && (
                <div>
                  <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
                    Affected Files ({active.files.length})
                  </span>
                  <div className="mt-1.5 flex flex-col gap-1">
                    {active.files.map((f) => (
                      <code
                        key={f}
                        className="text-xs font-mono px-2 py-1 rounded
                                   bg-surface-tertiary text-text-secondary
                                   block truncate"
                      >
                        {f}
                      </code>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export function PlanView({
  plan, duration, onReAdvise, onReFrame, isReviewing,
  onBack, onLoadIntoSession,
}: Props) {
  const [copied, setCopied] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedback, setFeedback] = useState("")

  const handleCopy = async () => {
    const text = formatPlanAsText(plan)
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleExport = () => {
    const text = formatPlanAsText(plan)
    const blob = new Blob([text], { type: "text/markdown" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${plan.plan_id}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  const notesSections = [
    { key: "arch", title: "Architecture", content: plan.architecture_notes },
    { key: "sec", title: "Security", content: plan.security_notes },
    { key: "qual", title: "Quality", content: plan.quality_notes },
    { key: "risk", title: "Risk Assessment", content: plan.risk_assessment },
    { key: "exec", title: "Execution Strategy", content: plan.execution_strategy },
  ].filter((s) => s.content)

  return (
    <div className="flex flex-col gap-6 py-6 px-6 max-w-6xl mx-auto w-full animate-card-enter">

      {/* ================================================================
          HEADER
          ================================================================ */}

      {/* Back link (history detail only) */}
      {onBack && (
        <button
          onClick={onBack}
          className="text-xs text-text-muted hover:text-text-secondary
                     transition-colors self-start -mb-4"
        >
          {"\u2190"} Back to history
        </button>
      )}

      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-semibold text-text-primary leading-tight">
            {plan.title}
          </h2>
          <p className="text-sm text-text-secondary mt-1.5 leading-relaxed">
            {plan.summary}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className={`px-2.5 py-1 text-xs rounded font-medium ${
              plan.risk_level === "HIGH"
                ? "bg-red-500/10 text-red-600 dark:text-red-400"
                : plan.risk_level === "MEDIUM"
                  ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                  : "bg-green-500/10 text-green-600 dark:text-green-400"
            }`}
          >
            {plan.risk_level}
          </span>
          <span className="px-2.5 py-1 text-xs rounded bg-accent/10 text-accent font-medium">
            {plan.estimated_effort}
          </span>
        </div>
      </div>

      {/* ── Re-advise in progress banner ── */}
      {isReviewing && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg
                        bg-amber-500/10 border border-amber-500/20">
          <span className="flex items-center gap-1 text-sm text-amber-600 dark:text-amber-400">
            <span className="animate-pulse-dot">.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
          </span>
          <span className="text-sm text-amber-600 dark:text-amber-400 font-medium">
            Re-advising -- new plan incoming
          </span>
        </div>
      )}

      {/* ── Metadata ── */}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-muted -mt-2">
        <span>Plan ID: <code className="font-mono text-text-secondary">{plan.plan_id}</code></span>
        {duration !== null && <span>Duration: {duration.toFixed(1)}s</span>}
        <span>{plan.implementation_steps.length} steps</span>
        <span>{plan.affected_files.length} files</span>
        {plan.negotiation_round > 0 && (
          <span>Round {plan.negotiation_round}</span>
        )}
      </div>

      {/* ================================================================
          GROUP: Advisor Notes  (tabbed -- zero layout shift)
          ================================================================ */}
      {notesSections.length > 0 && (
        <AdvisorNotesTabs sections={notesSections} />
      )}

      {/* ================================================================
          GROUP: Acceptance Criteria (plan-level)
          ================================================================ */}
      {plan.acceptance_criteria.length > 0 && (
        <div className="flex flex-col gap-3">
          <GroupHeading>Acceptance Criteria</GroupHeading>
          <div className="border border-border rounded-lg px-4 py-3">
            <ul className="space-y-1.5">
              {plan.acceptance_criteria.map((ac, i) => (
                <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                  <span className="text-accent mt-0.5 shrink-0">{"\u2713"}</span>
                  <span>{ac}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* ================================================================
          GROUP: Implementation (unified stories + steps + files)
          ================================================================ */}
      <ImplementationTabs plan={plan} />

      {/* ================================================================
          ACTION BAR
          ================================================================ */}
      <div className="border-t border-border pt-4 flex flex-col gap-3">
        <div className="flex items-center justify-between flex-wrap gap-3">
          {/* Left: export + history load */}
          <div className="flex gap-2">
            <button
              onClick={handleCopy}
              className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                         bg-accent text-white hover:opacity-90 transition-opacity"
            >
              {copied ? "Copied!" : "Copy plan"}
            </button>
            <button
              onClick={handleExport}
              className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                         border border-border text-text-secondary
                         hover:border-text-muted hover:text-text-primary
                         transition-colors"
            >
              Export .md
            </button>
            {onLoadIntoSession && (
              <button
                onClick={onLoadIntoSession}
                className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                           border border-accent text-accent
                           hover:bg-accent/10 transition-colors"
              >
                Load into session
              </button>
            )}
          </div>

          {/* Right: review */}
          {(onReAdvise || onReFrame) && (
            <div className="flex items-center gap-2">
              {onReFrame && (
                <button
                  onClick={onReFrame}
                  disabled={isReviewing}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                             border border-blue-500/30 text-blue-600 dark:text-blue-400
                             hover:bg-blue-500/10 transition-colors
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Re-frame
                </button>
              )}
              {onReAdvise && (
                <button
                  onClick={() => setShowFeedback(!showFeedback)}
                  disabled={isReviewing}
                  className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                             border border-amber-500/30 text-amber-600 dark:text-amber-400
                             hover:bg-amber-500/10 transition-colors
                             disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isReviewing ? "Re-advising..." : "Re-advise"}
                </button>
              )}
            </div>
          )}
        </div>

        {/* Feedback textarea (slides open) */}
        {showFeedback && onReAdvise && (
          <div className="flex gap-2 items-start animate-card-enter">
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="What should the advisors reconsider?"
              autoFocus
              className="flex-1 px-3 py-2 rounded-lg text-sm
                         bg-surface-secondary border border-border
                         text-text-primary placeholder:text-text-muted
                         focus:outline-none focus:ring-1 focus:ring-accent
                         resize-none"
              rows={2}
            />
            <div className="flex flex-col gap-1.5 shrink-0">
              <button
                onClick={() => {
                  if (feedback.trim()) {
                    onReAdvise(feedback.trim())
                    setShowFeedback(false)
                    setFeedback("")
                  }
                }}
                disabled={!feedback.trim() || isReviewing}
                className="px-3 py-1.5 rounded-lg text-xs font-medium
                           bg-amber-500/10 text-amber-600 dark:text-amber-400
                           border border-amber-500/30
                           hover:bg-amber-500/20 transition-colors
                           disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Send
              </button>
              <button
                onClick={() => { setShowFeedback(false); setFeedback("") }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium
                           text-text-muted hover:text-text-secondary
                           transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Text export ────────────────────────────────────────────────────────────

function formatPlanAsText(plan: ChangePlan): string {
  const lines: string[] = [
    `# ${plan.title}`,
    "",
    plan.summary,
    "",
    "## Implementation Steps",
    "",
  ]

  for (const step of plan.implementation_steps) {
    lines.push(`${step.order}. **${step.file_path}** (${step.action})`)
    lines.push(`   ${step.description}`)
    if (step.depends_on.length > 0) {
      lines.push(`   Depends on: ${step.depends_on.join(", ")}`)
    }
    lines.push("")
  }

  lines.push("## Affected Files", "")
  for (const f of plan.affected_files) lines.push(`- ${f}`)
  lines.push("")

  if (plan.architecture_notes) {
    lines.push("## Architecture Notes", "", plan.architecture_notes, "")
  }
  if (plan.security_notes) {
    lines.push("## Security Notes", "", plan.security_notes, "")
  }
  if (plan.quality_notes) {
    lines.push("## Quality Notes", "", plan.quality_notes, "")
  }
  if (plan.risk_assessment) {
    lines.push("## Risk Assessment", "", plan.risk_assessment, "")
  }
  if (plan.execution_strategy) {
    lines.push("## Execution Strategy", "", plan.execution_strategy, "")
  }

  if (plan.acceptance_criteria.length > 0) {
    lines.push("## Acceptance Criteria", "")
    for (const ac of plan.acceptance_criteria) lines.push(`- ${ac}`)
    lines.push("")
  }

  lines.push(`Risk: ${plan.risk_level} | Effort: ${plan.estimated_effort}`)

  return lines.join("\n")
}
