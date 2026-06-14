import { useCallback, useEffect, useState } from "react"
import type { TranscriptSummary } from "../types"

interface Props {
  onSubmit: (description: string) => void
  onLoadTranscript?: (planId: string) => void
}

export function DescriptionInput({ onSubmit, onLoadTranscript }: Props) {
  const [text, setText] = useState("")
  const [showTranscripts, setShowTranscripts] = useState(false)
  const [transcripts, setTranscripts] = useState<TranscriptSummary[]>([])
  const [loadingTranscripts, setLoadingTranscripts] = useState(false)

  const handleSubmit = () => {
    const trimmed = text.trim()
    if (trimmed) onSubmit(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const fetchTranscripts = useCallback(async () => {
    setLoadingTranscripts(true)
    try {
      const res = await fetch("/api/transcripts?limit=10")
      if (res.ok) {
        const data = await res.json()
        setTranscripts(data)
      }
    } catch {
      // Silent fail
    } finally {
      setLoadingTranscripts(false)
    }
  }, [])

  useEffect(() => {
    if (showTranscripts && transcripts.length === 0) {
      fetchTranscripts()
    }
  }, [showTranscripts, transcripts.length, fetchTranscripts])

  return (
    <div className="flex flex-col items-center gap-6 py-16 px-4">
      <div className="text-center">
        <h1 className="text-3xl font-semibold text-text-primary mb-2">
          Code Council
        </h1>
        <p className="text-text-secondary text-sm">
          Describe the feature or change you want to plan
        </p>
      </div>

      <div className="w-full max-w-xl">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Want to build a cash deposit feature..."
          rows={4}
          className="w-full px-4 py-3 rounded-lg border border-border
                     bg-surface text-text-primary text-sm
                     placeholder:text-text-muted
                     focus:outline-none focus:ring-2 focus:ring-accent/40
                     focus:border-accent resize-none"
          autoFocus
        />
        <div className="flex justify-between items-center mt-3">
          <div className="flex items-center gap-3">
            <span className="text-xs text-text-muted">
              {"\u2318"}+Enter to submit
            </span>
            {onLoadTranscript && (
              <button
                onClick={() => setShowTranscripts(!showTranscripts)}
                className="text-xs text-accent hover:text-accent/80 transition-colors"
              >
                {showTranscripts ? "Hide transcripts" : "Load from transcript"}
              </button>
            )}
          </div>
          <button
            onClick={handleSubmit}
            disabled={!text.trim()}
            className="px-5 py-2 rounded-lg text-sm font-medium
                       bg-accent text-white
                       hover:opacity-90 transition-opacity
                       disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Plan it
          </button>
        </div>
      </div>

      {/* Transcript list */}
      {showTranscripts && onLoadTranscript && (
        <div className="w-full max-w-xl border border-border rounded-lg overflow-hidden
                        animate-card-enter">
          <div className="px-4 py-2.5 bg-surface-secondary border-b border-border">
            <span className="text-xs font-medium text-text-primary">
              Recent Transcripts
            </span>
          </div>

          {loadingTranscripts ? (
            <div className="px-4 py-6 text-center text-xs text-text-muted">
              Loading...
            </div>
          ) : transcripts.length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-text-muted">
              No transcripts yet.
            </div>
          ) : (
            <div className="divide-y divide-border max-h-64 overflow-y-auto">
              {transcripts.map((t) => (
                <button
                  key={t.plan_id}
                  onClick={() => onLoadTranscript(t.plan_id)}
                  className="w-full flex items-center gap-3 px-4 py-3
                             hover:bg-surface-secondary transition-colors text-left"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-text-primary truncate">
                      {t.question || t.plan_id}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-xs text-text-muted">
                        {new Date(t.timestamp).toLocaleDateString()}
                      </span>
                      <span className="text-xs text-text-muted">
                        {t.message_count} messages
                      </span>
                      {t.has_framed_question && (
                        <span className="px-1.5 py-px text-[10px] rounded bg-green-500/10
                                         text-green-600 dark:text-green-400">
                          framed
                        </span>
                      )}
                      {t.status === "review" && (
                        <span className="px-1.5 py-px text-[10px] rounded bg-amber-500/10
                                         text-amber-600 dark:text-amber-400">
                          review
                        </span>
                      )}
                    </div>
                  </div>
                  <span className="text-text-muted text-xs shrink-0">{"\u2192"}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
