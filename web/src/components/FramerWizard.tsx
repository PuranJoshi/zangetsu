import { useRef, useEffect, useState } from "react"
import type { FramerMessage, FramerStatus } from "../types"
import { MarkdownContent } from "./MarkdownContent"
import { ErrorDisplay } from "./ErrorDisplay"

interface Props {
  messages: FramerMessage[]
  status: FramerStatus
  error: string | null
  onReply: (text: string) => void
  onSkip: () => void
}

export function FramerWizard({ messages, status, error, onReply, onSkip }: Props) {
  const [customText, setCustomText] = useState("")
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [_showCustom, setShowCustom] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const latestFramer = [...messages].reverse().find((m) => m.role === "framer")
  const hasChoices = latestFramer?.choices && latestFramer.choices.length > 0
  const isWaiting = status === "chatting"

  const handleChoiceClick = (choice: string) => {
    setShowCustom(false)
    setCustomText("")
    onReply(choice)
  }

  const handleCustomSubmit = () => {
    const trimmed = customText.trim()
    if (!trimmed) return
    setCustomText("")
    setShowCustom(false)
    onReply(trimmed)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleCustomSubmit()
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-3.5rem)] max-w-4xl mx-auto w-full px-6">
      {/* Header */}
      <div className="flex justify-between items-center py-4 shrink-0">
        <h2 className="text-lg font-medium text-text-primary">
          Framing your request
        </h2>
        {status !== "done" && (
          <button
            onClick={onSkip}
            className="text-xs text-text-muted hover:text-text-secondary
                       transition-colors px-3 py-1 rounded border border-border
                       hover:border-text-muted"
          >
            Skip -- just frame it
          </button>
        )}
      </div>

      {/* Messages -- fills available space, scrolls */}
      <div className="flex-1 min-h-0 overflow-y-auto pr-1 scroll-on-hover">
        <div className="flex flex-col gap-3 py-2">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`rounded-lg px-4 py-3 text-sm animate-card-enter max-w-[80%] ${
                msg.role === "user"
                  ? "bg-accent/10 text-text-primary self-end"
                  : "bg-surface-secondary border border-border self-start"
              }`}
            >
              <MarkdownContent content={msg.text} />
            </div>
          ))}

          {/* Thinking indicator */}
          {status === "thinking" && (
            <div className="bg-surface-secondary border border-border rounded-lg
                            px-4 py-3 text-sm self-start flex items-center gap-1
                            max-w-[80%]">
              <span className="animate-pulse-dot" style={{ animationDelay: "0ms" }}>.</span>
              <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
              <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
              <span className="text-text-muted ml-1">Thinking</span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input area -- pinned at bottom */}
      <div className="shrink-0 border-t border-border pt-3 pb-4 flex flex-col gap-2">
        {/* Error */}
        {error && (
          <ErrorDisplay message={error} compact onDismiss={onSkip} />
        )}

        {/* Choice buttons */}
        {isWaiting && hasChoices && (
          <div className="flex flex-wrap gap-2">
            {latestFramer!.choices!.map((choice, i) => (
              <button
                key={i}
                onClick={() => handleChoiceClick(choice)}
                className="px-4 py-2 rounded-full text-sm border border-border
                           bg-surface-secondary text-text-primary
                           hover:border-accent hover:bg-accent/5
                           transition-colors"
              >
                {choice}
              </button>
            ))}
          </div>
        )}

        {/* Text input -- always visible when waiting */}
        {isWaiting && (
          <div className="flex gap-2">
            <input
              type="text"
              value={customText}
              onChange={(e) => setCustomText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={hasChoices ? "Or type your own answer..." : "Your answer..."}
              className="flex-1 px-3 py-2 rounded-lg border border-border
                         bg-surface text-sm text-text-primary
                         placeholder:text-text-muted
                         focus:outline-none focus:ring-2 focus:ring-accent/40"
              autoFocus
            />
            <button
              onClick={handleCustomSubmit}
              disabled={!customText.trim()}
              className="px-4 py-2 rounded-lg text-sm bg-accent text-white
                         hover:opacity-90 disabled:opacity-40
                         disabled:cursor-not-allowed transition-opacity"
            >
              Send
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
