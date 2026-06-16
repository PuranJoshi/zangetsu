import { useCallback, useEffect, useMemo, useState } from "react"
import type { TranscriptSummary } from "../types"

interface Props {
  onSubmit: (description: string) => void
  onLoadTranscript?: (planId: string) => void
}

/* ------------------------------------------------------------------ */
/*  Tree node: a transcript with its resolved children                 */
/* ------------------------------------------------------------------ */

interface TreeNode {
  transcript: TranscriptSummary
  children: TreeNode[]
}

/* ------------------------------------------------------------------ */
/*  Transcript card                                                    */
/* ------------------------------------------------------------------ */

function TranscriptCard({
  t,
  onLoad,
}: {
  t: TranscriptSummary
  onLoad: (id: string) => void
}) {
  return (
    <button
      onClick={() => onLoad(t.plan_id)}
      className="w-full text-left px-3 py-2 rounded-lg border border-border
                 bg-surface hover:bg-surface-secondary hover:border-accent/40
                 transition-colors group"
    >
      <p className="text-sm text-text-primary truncate">
        {t.question || t.plan_id}
      </p>
      <div className="flex items-center gap-2 mt-1">
        <span className="text-[10px] font-mono text-text-muted/50">
          {t.plan_id}
        </span>
        <span className="text-[10px] text-text-muted">
          {new Date(t.timestamp).toLocaleDateString()}
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
        <span className="ml-auto text-text-muted/0 group-hover:text-accent
                         text-xs transition-colors">
          {"\u2192"}
        </span>
      </div>
    </button>
  )
}

/* ------------------------------------------------------------------ */
/*  Recursive tree: parent at top, ancestors indented below            */
/*  (tree is inverted: newest revision is root, original is leaf)      */
/* ------------------------------------------------------------------ */

function TreeChildren({
  children,
  onLoad,
}: {
  children: TreeNode[]
  onLoad: (id: string) => void
}) {
  if (children.length === 0) return null

  return (
    <div className="relative ml-5 pl-5">
      {children.map((child, i) => {
        const isLast = i === children.length - 1
        return (
          <div key={child.transcript.plan_id} className="relative py-1">
            {/* Vertical line from above */}
            <div
              className="absolute left-[-20px] w-px bg-border"
              style={{ top: 0, bottom: "50%" }}
            />
            {/* Vertical line continues down unless last sibling */}
            {!isLast && (
              <div
                className="absolute left-[-20px] w-px bg-border"
                style={{ top: "50%", bottom: 0 }}
              />
            )}
            {/* Horizontal branch */}
            <div
              className="absolute top-1/2 h-px bg-border"
              style={{ left: -20, width: 20, transform: "translateY(-0.5px)" }}
            />
            {/* Junction dot */}
            <div
              className="absolute w-1.5 h-1.5 rounded-full bg-border"
              style={{ left: -23, top: "50%", transform: "translate(0, -50%)" }}
            />

            {/* The node card */}
            <TranscriptCard t={child.transcript} onLoad={onLoad} />

            {/* Recurse into deeper ancestors */}
            <TreeChildren children={child.children} onLoad={onLoad} />
          </div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Top-level tree group: root node + its ancestors below              */
/* ------------------------------------------------------------------ */

function TreeGroup({
  node,
  onLoad,
}: {
  node: TreeNode
  onLoad: (id: string) => void
}) {
  return (
    <div className="py-1">
      <TranscriptCard t={node.transcript} onLoad={onLoad} />
      <TreeChildren children={node.children} onLoad={onLoad} />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Build tree from flat transcript list                               */
/* ------------------------------------------------------------------ */

function buildTree(transcripts: TranscriptSummary[]): TreeNode[] {
  // Index by plan_id
  const byId = new Map<string, TranscriptSummary>()
  for (const t of transcripts) {
    byId.set(t.plan_id, t)
  }

  // Find which IDs are someone else's base_plan_id (i.e. they have a child
  // in the visible list, so they are NOT a leaf/tip).
  const hasChild = new Set<string>()
  for (const t of transcripts) {
    if (t.base_plan_id && byId.has(t.base_plan_id)) {
      hasChild.add(t.base_plan_id)
    }
  }

  // Roots of the inverted tree = leaf tips (no children) = newest in each chain.
  // Standalone transcripts (no base_plan_id AND no children) are also roots.
  const tips = transcripts.filter((t) => !hasChild.has(t.plan_id))

  // For each tip, walk the base_plan_id chain downward to build the
  // inverted tree: tip at top, ancestors as children below.
  function toInvertedNode(t: TranscriptSummary, visited: Set<string>): TreeNode {
    visited.add(t.plan_id)
    const parent = t.base_plan_id ? byId.get(t.base_plan_id) : undefined
    const children: TreeNode[] = []
    if (parent && !visited.has(parent.plan_id)) {
      children.push(toInvertedNode(parent, visited))
    }
    return { transcript: t, children }
  }

  // Track which transcripts are consumed (nested under a tip) so we
  // don't show them as separate roots too.
  const consumed = new Set<string>()

  const roots: TreeNode[] = []
  for (const tip of tips) {
    const visited = new Set<string>()
    const node = toInvertedNode(tip, visited)
    roots.push(node)
    for (const id of visited) consumed.add(id)
  }

  // Sort roots newest first
  roots.sort((a, b) =>
    b.transcript.timestamp.localeCompare(a.transcript.timestamp)
  )

  return roots
}

/* ------------------------------------------------------------------ */
/*  Main component                                                     */
/* ------------------------------------------------------------------ */

export function DescriptionInput({ onSubmit, onLoadTranscript }: Props) {
  const [text, setText] = useState("")
  const [searchId, setSearchId] = useState("")
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

  // Always fetch on mount
  useEffect(() => {
    if (onLoadTranscript) {
      void fetchTranscripts()
    }
  }, [onLoadTranscript, fetchTranscripts])

  const roots = useMemo(() => buildTree(transcripts), [transcripts])

  const hasTranscripts = transcripts.length > 0

  return (
    <div className="flex flex-col h-[calc(100dvh-3.5rem)]">
      {/* Input area */}
      <div className={`flex flex-col items-center gap-6 px-4 shrink-0
                       ${hasTranscripts ? "py-8" : "py-12"}`}>
        <div className="text-center">
          <h1 className="text-3xl font-semibold text-text-primary mb-2">
            Zangetsu: AI Planning Council
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
            rows={3}
            className="w-full px-4 py-3 rounded-lg border border-border
                       bg-surface text-text-primary text-sm
                       placeholder:text-text-muted
                       focus:outline-none focus:ring-2 focus:ring-accent/40
                       focus:border-accent resize-none"
            autoFocus
          />
          <div className="flex justify-between items-center mt-3">
            <span className="text-xs text-text-muted">
              {"\u2318"}+Enter to submit
            </span>
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
      </div>

      {/* Transcript family tree -- always visible, fills remaining height */}
      {onLoadTranscript && (
        <div className="flex-1 min-h-0 flex flex-col items-center">
          <div className="w-full max-w-2xl flex flex-col flex-1 min-h-0">
            {/* Header: title + plan ID search */}
            <div className="px-4 pt-2 pb-1 shrink-0 flex items-center justify-between gap-3">
              <span className="text-xs font-medium text-text-muted uppercase tracking-wide">
                Recent Sessions
              </span>
              <form
                className="flex items-center gap-1.5"
                onSubmit={(e) => {
                  e.preventDefault()
                  const id = searchId.trim()
                  if (id) {
                    onLoadTranscript(id)
                    setSearchId("")
                  }
                }}
              >
                <input
                  type="text"
                  value={searchId}
                  onChange={(e) => setSearchId(e.target.value)}
                  placeholder="plan id"
                  className="w-28 px-2 py-1 text-xs font-mono rounded border border-border
                             bg-surface text-text-primary placeholder:text-text-muted/50
                             focus:outline-none focus:ring-1 focus:ring-accent/40
                             focus:border-accent"
                />
                <button
                  type="submit"
                  disabled={!searchId.trim()}
                  className="px-2 py-1 text-xs rounded border border-border
                             text-text-secondary hover:text-text-primary
                             hover:border-accent/40 transition-colors
                             disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  Load
                </button>
              </form>
            </div>

            {loadingTranscripts ? (
              <div className="py-6 text-center text-xs text-text-muted">
                Loading...
              </div>
            ) : !hasTranscripts ? (
              <div className="py-6 text-center text-xs text-text-muted">
                No recent sessions
              </div>
            ) : (
              <div className="flex-1 min-h-0 overflow-y-auto px-4 pb-4
                              space-y-1">
                {roots.map((node) => (
                  <TreeGroup
                    key={node.transcript.plan_id}
                    node={node}
                    onLoad={onLoadTranscript}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
