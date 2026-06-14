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

  // Progress percentage along the track
  const progress = isDone ? 100 : isError ? ((ci / total) * 100) : (((ci + 0.5) / total) * 100)

  return (
    <div className="relative h-6">
      {/* Track background */}
      <div className="absolute left-0 right-0 top-[11px] h-[3px] rounded-full bg-surface-tertiary" />

      {/* Filled track */}
      <div
        className={`absolute left-0 top-[11px] h-[3px] rounded-full transition-all duration-700 ease-out ${
          isError ? "bg-red-500" : isDone ? "bg-green-500" : "bg-accent"
        }`}
        style={{ width: `${progress}%` }}
      />

      {/* Animated car/dot on the progress front */}
      {!isDone && !isError && (
        <div
          className="absolute top-[5px] w-4 h-4 -ml-2 transition-all duration-700 ease-out"
          style={{ left: `${progress}%` }}
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

      {/* Finish flag when done */}
      {isDone && (
        <div
          className="absolute top-0 -translate-x-1/2 flex flex-col items-center"
          style={{ left: "100%" }}
        >
          <div className="w-[9px] h-[9px] rounded-full bg-green-500 border-2 border-green-500 mt-[7px]" />
        </div>
      )}
    </div>
  )
}
