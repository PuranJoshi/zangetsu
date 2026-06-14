import { useState } from "react"
import { ADVISOR_CONFIG } from "../types"
import { MarkdownContent } from "./MarkdownContent"

interface Props {
  name: string
  response: string
  animate?: boolean
}

export function AdvisorCard({ name, response, animate = true }: Props) {
  const [expanded, setExpanded] = useState(true)
  const config = ADVISOR_CONFIG[name] || {
    color: "#6b7280",
    icon: "\u2022",
    shortDesc: name,
  }

  return (
    <div
      className={`border border-border rounded-lg overflow-hidden
                  ${animate ? "animate-card-enter" : ""}`}
      style={{ borderLeftColor: config.color, borderLeftWidth: 3 }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3
                   hover:bg-surface-secondary transition-colors text-left"
      >
        <div className="flex items-center gap-2">
          <span
            className="w-6 h-6 rounded flex items-center justify-center text-sm"
            style={{ backgroundColor: `${config.color}20`, color: config.color }}
          >
            {config.icon}
          </span>
          <div>
            <span className="text-sm font-medium text-text-primary">{name}</span>
            <span className="text-xs text-text-muted ml-2">{config.shortDesc}</span>
          </div>
        </div>
        <span className="text-text-muted text-xs">{expanded ? "\u25B2" : "\u25BC"}</span>
      </button>

      {expanded && (
        <div className="px-4 py-3 border-t border-border">
          <MarkdownContent content={response} />
        </div>
      )}
    </div>
  )
}
