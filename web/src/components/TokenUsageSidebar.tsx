import type { TokenUsageState } from "../types"

// ---------------------------------------------------------------------------
// Number formatting helper
// ---------------------------------------------------------------------------

function formatNumber(n: number): string {
  return n.toLocaleString()
}

// ---------------------------------------------------------------------------
// TokenUsageSidebar
// ---------------------------------------------------------------------------

interface Props {
  tokenUsage: TokenUsageState | null
}

export function TokenUsageSidebar({ tokenUsage }: Props) {
  return (
    <div className="flex flex-col flex-1 min-h-0 border-t border-border">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-border">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          Token Usage
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto scroll-on-hover">
        {!tokenUsage ? (
          <div className="px-3 py-6 text-center text-text-muted text-xs">
            No active session
          </div>
        ) : (
          <div className="py-1">
            {/* Per-stage rows */}
            {tokenUsage.stages.map((s) => (
              <div
                key={s.stage}
                className="flex items-center justify-between px-3 py-1.5"
              >
                <span className="text-xs text-text-secondary capitalize truncate">
                  {s.stage}
                </span>
                <span className="text-xs text-text-muted font-mono">
                  {formatNumber(s.usage.total_tokens)}
                </span>
              </div>
            ))}

            {/* Separator + total */}
            <div className="mx-3 my-1.5 border-t border-border" />
            <div className="flex items-center justify-between px-3 py-1.5">
              <span className="text-xs font-semibold text-text-primary">
                Total
              </span>
              <span className="text-xs font-semibold text-text-primary font-mono">
                {formatNumber(tokenUsage.total.total_tokens)}
              </span>
            </div>

            {/* Prompt / completion breakdown */}
            <div className="px-3 pb-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Prompt</span>
                <span className="text-[10px] text-text-muted font-mono">
                  {formatNumber(tokenUsage.total.prompt_tokens)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-text-muted">Completion</span>
                <span className="text-[10px] text-text-muted font-mono">
                  {formatNumber(tokenUsage.total.completion_tokens)}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
