import { useCallback, useEffect, useState } from "react"
import type { FramedRequirement } from "../types"
import { ErrorDisplay } from "./ErrorDisplay"

interface Props {
  isScanning: boolean
  error: string | null
  onUploadContext: (contextJson: string) => void
  onSkip: () => void
  changeDescription: string
  framedRequirement: FramedRequirement | null
}

export function ProjectScanner({
  isScanning,
  error,
  onUploadContext,
  onSkip,
  changeDescription,
  framedRequirement,
}: Props) {
  const [aiPrompt, setAiPrompt] = useState<string | null>(null)
  const [promptLoading, setPromptLoading] = useState(false)
  const [contextJson, setContextJson] = useState("")
  const [copied, setCopied] = useState(false)

  // Fetch the AI prompt on mount
  const fetchPrompt = useCallback(async () => {
    setPromptLoading(true)
    try {
      const res = await fetch("/api/scan/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          change_description: changeDescription,
          framed_requirement: framedRequirement,
        }),
      })
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }
      const data = await res.json()
      setAiPrompt(data.prompt)
    } catch {
      setAiPrompt("Failed to generate prompt. Please try again.")
    } finally {
      setPromptLoading(false)
    }
  }, [changeDescription, framedRequirement])

  useEffect(() => {
    if (!aiPrompt && !promptLoading) {
      fetchPrompt()
    }
  }, [aiPrompt, promptLoading, fetchPrompt])

  const handleCopyPrompt = useCallback(async () => {
    if (!aiPrompt) return
    try {
      await navigator.clipboard.writeText(aiPrompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // Fallback: select the text
    }
  }, [aiPrompt])

  const handleUpload = () => {
    const trimmed = contextJson.trim()
    if (!trimmed) return
    onUploadContext(trimmed)
  }

  return (
    <div className="flex flex-col gap-5 py-6 px-4 max-w-2xl mx-auto w-full">
      <div className="flex justify-between items-center">
        <h2 className="text-lg font-medium text-text-primary">
          Project Context
        </h2>
        <button
          onClick={onSkip}
          className="text-xs text-text-muted hover:text-text-secondary
                     transition-colors px-3 py-1 rounded border border-border
                     hover:border-text-muted"
        >
          Skip (greenfield)
        </button>
      </div>

      <p className="text-sm text-text-secondary">
        Generate project context with your AI coding tool so advisors can give
        file-level recommendations.
      </p>

      {/* Upload error */}
      {error && (
        <ErrorDisplay
          message={error}
          compact
          onRetry={fetchPrompt}
          onDismiss={onSkip}
        />
      )}

      {!isScanning && (
        <div className="space-y-4">
          {/* Step 1: Show the generated prompt */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-text-primary">
                Step 1: Copy this prompt into your AI coding tool
              </h3>
              <button
                onClick={handleCopyPrompt}
                disabled={!aiPrompt || promptLoading}
                className="text-xs px-3 py-1 rounded border border-border
                           hover:border-accent text-text-secondary hover:text-accent
                           transition-colors disabled:opacity-40"
              >
                {copied ? "Copied!" : "Copy"}
              </button>
            </div>
            <p className="text-xs text-text-muted">
              Open your AI tool in the target repository and paste this prompt.
              It will analyze the codebase and return a JSON object tailored to
              your planned change.
            </p>
            {promptLoading ? (
              <div className="px-4 py-8 rounded-lg border border-border bg-surface-tertiary
                              text-sm text-text-muted text-center">
                Generating prompt...
              </div>
            ) : (
              <pre
                className="px-4 py-3 rounded-lg border border-border bg-surface-tertiary
                           text-xs font-mono text-text-secondary max-h-64 overflow-auto
                           whitespace-pre-wrap cursor-text select-all"
              >
                {aiPrompt}
              </pre>
            )}
          </div>

          {/* Step 2: Paste the JSON back */}
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-text-primary">
              Step 2: Paste the JSON output here
            </h3>
            <p className="text-xs text-text-muted">
              Copy the JSON that your AI tool produced and paste it below.
            </p>
            <textarea
              value={contextJson}
              onChange={(e) => setContextJson(e.target.value)}
              placeholder='{"project_path": "...", "directory_tree": "...", ...}'
              rows={8}
              className="w-full px-3 py-2 rounded-lg border border-border
                         bg-surface text-xs text-text-primary font-mono
                         placeholder:text-text-muted resize-y
                         focus:outline-none focus:ring-2 focus:ring-accent/40"
            />
            <button
              onClick={handleUpload}
              disabled={!contextJson.trim()}
              className="px-5 py-2 rounded-lg text-sm font-medium
                         bg-accent text-white hover:opacity-90
                         disabled:opacity-40 disabled:cursor-not-allowed
                         transition-opacity"
            >
              Upload & continue
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
