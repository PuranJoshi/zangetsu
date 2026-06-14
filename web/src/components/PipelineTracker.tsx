import type { SessionStage } from "../types"

interface Props {
  currentStage: SessionStage
  advisorsDone: number
  advisorsTotal: number
}

const STAGES: { key: SessionStage; label: string }[] = [
  { key: "framing", label: "Framing" },
  { key: "confirming", label: "Review" },
  { key: "scanning", label: "Scan" },
  { key: "advising", label: "Advisors" },
  { key: "synthesizing", label: "Synthesis" },
  { key: "completed", label: "Plan" },
]

const STAGE_ORDER: Record<string, number> = {}
STAGES.forEach((s, i) => { STAGE_ORDER[s.key] = i })

function stageStatus(
  stage: SessionStage,
  current: SessionStage
): "done" | "active" | "pending" {
  const ci = STAGE_ORDER[current] ?? -1
  const si = STAGE_ORDER[stage] ?? -1
  if (current === "completed" && stage === "completed") return "done"
  if (current === "error") return si <= ci ? "done" : "pending"
  if (si < ci) return "done"
  if (si === ci) return "active"
  return "pending"
}

export function PipelineTracker({ currentStage, advisorsDone, advisorsTotal }: Props) {
  if (currentStage === "idle") return null

  return (
    <div className="flex items-center justify-center gap-1 py-4 px-4">
      {STAGES.map((stage, i) => {
        const status = stageStatus(stage.key, currentStage)
        return (
          <div key={stage.key} className="flex items-center">
            {/* Stage indicator */}
            <div className="flex flex-col items-center gap-1">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center
                            text-xs font-medium transition-colors ${
                  status === "done"
                    ? "bg-green-500 text-white"
                    : status === "active"
                      ? "bg-accent text-white"
                      : "bg-surface-tertiary text-text-muted"
                }`}
              >
                {status === "done" ? (
                  "\u2713"
                ) : status === "active" ? (
                  <span className="animate-pulse-dot">{"\u2022"}</span>
                ) : (
                  <span className="text-[10px]">{i + 1}</span>
                )}
              </div>
              <span
                className={`text-[10px] ${
                  status === "active"
                    ? "text-accent font-medium"
                    : status === "done"
                      ? "text-green-600 dark:text-green-400"
                      : "text-text-muted"
                }`}
              >
                {stage.key === "advising" && status === "active"
                  ? `${advisorsDone}/${advisorsTotal}`
                  : stage.label}
              </span>
            </div>

            {/* Connector line */}
            {i < STAGES.length - 1 && (
              <div
                className={`w-6 h-px mx-1 ${
                  stageStatus(STAGES[i + 1].key, currentStage) !== "pending"
                    ? "bg-green-500"
                    : status === "active"
                      ? "bg-accent/30"
                      : "bg-border"
                }`}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
