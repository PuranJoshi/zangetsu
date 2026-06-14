interface Props {
  message: string
  onRetry?: () => void
  onDismiss?: () => void
  /** Compact variant for inline use (no card wrapper). */
  compact?: boolean
}

export function ErrorDisplay({ message, onRetry, onDismiss, compact }: Props) {
  if (compact) {
    return (
      <div className="flex items-center gap-3 text-sm text-red-600 dark:text-red-400
                      bg-red-500/10 px-4 py-2.5 rounded-lg animate-card-enter">
        <span className="flex-1 min-w-0">{message}</span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="shrink-0 text-xs font-medium px-2.5 py-1 rounded
                       border border-red-500/30 hover:bg-red-500/10
                       transition-colors"
          >
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="shrink-0 text-xs text-text-muted hover:text-text-secondary
                       transition-colors"
          >
            Dismiss
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="mx-4 my-6 p-5 rounded-lg bg-red-500/10 border border-red-500/30
                    animate-card-enter max-w-2xl mx-auto">
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-3">
          <span className="text-red-500 text-lg shrink-0 mt-0.5">!</span>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-medium text-red-600 dark:text-red-400">
              Something went wrong
            </h3>
            <p className="text-sm text-red-600/80 dark:text-red-400/80 mt-1 leading-relaxed">
              {message}
            </p>
          </div>
        </div>

        <div className="flex gap-2 pt-1">
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                         bg-red-500/10 text-red-600 dark:text-red-400
                         border border-red-500/30 hover:bg-red-500/20
                         transition-colors"
            >
              Try again
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="px-3.5 py-1.5 rounded-lg text-xs font-medium
                         text-text-muted hover:text-text-secondary
                         transition-colors"
            >
              Back to home
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
