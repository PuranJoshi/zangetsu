import type { SessionStage } from "../types"

interface Props {
  currentStage: SessionStage
  advisorsDone: number
  advisorsTotal: number
}

const STAGES: { key: SessionStage; label: string; icon: string }[] = [
  { key: "framing", label: "Frame", icon: "\u{1F3C1}" },      // flag
  { key: "confirming", label: "Review", icon: "\u25C6" },      // diamond
  { key: "scanning", label: "Scan", icon: "\u25C6" },
  { key: "advising", label: "Advise", icon: "\u25C6" },
  { key: "analyzing", label: "Analyze", icon: "\u25C6" },
  { key: "synthesizing", label: "Synth", icon: "\u25C6" },
  { key: "completed", label: "Finish", icon: "\u{1F3C1}" },   // flag
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

  const ci = STAGE_ORDER[currentStage] ?? 0
  const total = STAGES.length - 1 // segments between checkpoints
  const isError = currentStage === "error"
  const isDone = currentStage === "completed"

  // Dot sits exactly on the current active checkpoint
  const dotPosition = isDone ? 100 : (ci / total) * 100

  // Determine segment colors: each segment connects STAGES[i] to STAGES[i+1]
  // - Green: completed segments AND the segment leading into the active step
  // - Gray: everything ahead of the active step
  const segmentColors = STAGES.slice(0, -1).map((_, i) => {
    const leftStatus = stageStatus(STAGES[i].key, currentStage)
    const rightStatus = stageStatus(STAGES[i + 1].key, currentStage)
    // Both endpoints done → green (completed segment)
    if (leftStatus === "done" && rightStatus === "done") return "bg-green-500"
    // Left done, right is active → green all the way to the active dot
    if (leftStatus === "done" && rightStatus === "active") return "bg-green-500"
    // Error: segments up to error point are red
    if (isError && leftStatus === "done") return "bg-red-500"
    // Everything else stays gray
    return "bg-surface-tertiary"
  })

  return (
    <div className="relative h-6">
      {/* Per-segment track lines */}
      {STAGES.slice(0, -1).map((_, i) => {
        const leftPct = (i / total) * 100
        const rightPct = ((i + 1) / total) * 100
        const color = segmentColors[i]

        return (
          <div
            key={`seg-${i}`}
            className={`absolute top-[11px] h-[3px] transition-colors duration-700 ease-out ${color}`}
            style={{ left: `${leftPct}%`, width: `${rightPct - leftPct}%` }}
          />
        )
      })}

      {/* Animated dot sitting on the current active checkpoint */}
      {!isDone && !isError && (
        <div
          className="absolute top-[5px] w-4 h-4 -ml-2 transition-all duration-700 ease-out"
          style={{ left: `${dotPosition}%` }}
        >
          <div className="w-4 h-4 rounded-full bg-accent shadow-[0_0_8px_rgba(99,102,241,0.5)]
                          flex items-center justify-center animate-pulse">
            <div className="w-1.5 h-1.5 rounded-full bg-white" />
          </div>
        </div>
      )}

      {/* Checkpoints */}
      {STAGES.map((stage, i) => {
        const status = stageStatus(stage.key, currentStage)
        const pct = (i / total) * 100
        const label =
          stage.key === "advising" && status === "active"
            ? `${advisorsDone}/${advisorsTotal}`
            : stage.label

        return (
          <div
            key={stage.key}
            className="absolute top-0 -translate-x-1/2 flex flex-col items-center"
            style={{ left: `${pct}%` }}
          >
            {/* Checkpoint marker */}
            <div
              className={`w-[9px] h-[9px] rounded-full border-2 transition-colors mt-[7px] ${
                status === "done"
                  ? "bg-green-500 border-green-500"
                  : status === "active"
                    ? "bg-accent border-accent"
                    : "bg-surface border-border"
              }`}
            />
            {/* Label below */}
            <span
              className={`text-[9px] mt-1 whitespace-nowrap transition-colors ${
                status === "active"
                  ? "text-accent font-semibold"
                  : status === "done"
                    ? "text-green-600 dark:text-green-400"
                    : "text-text-muted/50"
              }`}
            >
              {label}
            </span>
          </div>
        )
      })}
    </div>
  )
}
