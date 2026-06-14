import { useRef, useEffect, useState } from "react"
import type { FramerMessage, FramerStatus } from "../types"
import { MarkdownContent } from "./MarkdownContent"

interface Props {
  messages: FramerMessage[]
  status: FramerStatus
  error: string | null
  onReply: (text: string) => void
  onSkip: () => void
}

export function FramerWizard({ messages, status, error, onReply, onSkip }: Props) {
  const [customText, setCustomText] = useState("")
  const [showCustom, setShowCustom] = useState(false)
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
    <div className="flex flex-col gap-4 py-6 px-4 max-w-xl mx-auto w-full">
      {/* Header */}
      <div className="flex justify-between items-center">
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

      {/* Messages */}
      <div className="flex flex-col gap-3 max-h-[60vh] overflow-y-auto pr-1">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`rounded-lg px-4 py-3 text-sm animate-card-enter ${
              msg.role === "user"
                ? "bg-accent/10 text-text-primary ml-8 self-end"
                : "bg-surface-secondary border border-border mr-8 self-start"
            }`}
          >
            <MarkdownContent content={msg.text} />
          </div>
        ))}

        {/* Thinking indicator */}
        {status === "thinking" && (
          <div className="bg-surface-secondary border border-border rounded-lg
                          px-4 py-3 text-sm mr-8 self-start flex items-center gap-1">
            <span className="animate-pulse-dot" style={{ animationDelay: "0ms" }}>.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "200ms" }}>.</span>
            <span className="animate-pulse-dot" style={{ animationDelay: "400ms" }}>.</span>
            <span className="text-text-muted ml-1">Thinking</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Choice buttons (when waiting for reply with choices) */}
      {isWaiting && hasChoices && (
        <div className="flex flex-col gap-2">
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

          {!showCustom ? (
            <button
              onClick={() => setShowCustom(true)}
              className="text-xs text-text-muted hover:text-accent
                         self-start mt-1 transition-colors"
            >
              Type your own answer
            </button>
          ) : (
            <div className="flex gap-2 mt-1">
              <input
                type="text"
                value={customText}
                onChange={(e) => setCustomText(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Your answer..."
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
      )}

      {/* Open text input (when waiting but no choices) */}
      {isWaiting && !hasChoices && (
        <div className="flex gap-2">
          <input
            type="text"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Your answer..."
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

      {/* Error */}
      {error && (
        <div className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">
          {error}
        </div>
      )}
    </div>
  )
}
