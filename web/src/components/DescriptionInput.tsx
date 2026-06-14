import { useState } from "react"

interface Props {
  onSubmit: (description: string) => void
}

export function DescriptionInput({ onSubmit }: Props) {
  const [text, setText] = useState("")

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
  )
}
