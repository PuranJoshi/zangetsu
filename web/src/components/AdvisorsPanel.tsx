import type { AdvisorResponse } from "../types"
import { ADVISOR_CONFIG } from "../types"
import { AdvisorCard } from "./AdvisorCard"

interface Props {
  advisorNames: string[]
  advisorResponses: AdvisorResponse[]
  isComplete: boolean
}

export function AdvisorsPanel({ advisorNames, advisorResponses, isComplete }: Props) {
  const completedNames = new Set(advisorResponses.map((a) => a.name))

  return (
    <div className="flex flex-col gap-4 py-4 px-4 max-w-2xl mx-auto w-full">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-medium text-text-primary">Advisors</h2>
        <span className="text-xs text-text-muted">
          {advisorResponses.length}/{advisorNames.length}{" "}
          {isComplete ? "complete" : "responding"}
        </span>
      </div>

      <div className="space-y-3">
        {/* Completed advisors */}
        {advisorResponses.map((advisor) => (
          <AdvisorCard
            key={advisor.name}
            name={advisor.name}
            response={advisor.response}
          />
        ))}

        {/* Pending advisors */}
        {advisorNames
          .filter((name) => !completedNames.has(name))
          .map((name) => {
            const config = ADVISOR_CONFIG[name] || {
              color: "#6b7280",
              icon: "\u2022",
              shortDesc: name,
            }
            return (
              <div
                key={name}
                className="border border-border rounded-lg px-4 py-3
                           flex items-center gap-2"
                style={{ borderLeftColor: config.color, borderLeftWidth: 3 }}
              >
                <span
                  className="w-6 h-6 rounded flex items-center justify-center text-sm"
                  style={{
                    backgroundColor: `${config.color}20`,
                    color: config.color,
                  }}
                >
                  {config.icon}
                </span>
                <span className="text-sm text-text-secondary">{name}</span>
                <span className="ml-auto flex items-center gap-1 text-xs text-text-muted">
                  <span className="animate-pulse-dot">.</span>
                  <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
                  <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
                  <span className="ml-1">Thinking</span>
                </span>
              </div>
            )
          })}
      </div>
    </div>
  )
}
