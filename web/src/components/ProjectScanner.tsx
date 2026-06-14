import { useState } from "react"
import type { DiscoveredFile, ScanTreeResult } from "../types"

interface Props {
  treeResult: ScanTreeResult | null
  discoveredFiles: DiscoveredFile[]
  isScanning: boolean
  onScanPath: (path: string) => void
  onDiscover: (path: string, description: string) => void
  onApprove: (path: string, approvedPaths: string[], configFiles?: string[]) => void
  onSkip: () => void
  changeDescription: string
}

export function ProjectScanner({
  treeResult,
  discoveredFiles,
  isScanning,
  onScanPath,
  onDiscover,
  onApprove,
  onSkip,
  changeDescription,
}: Props) {
  const [projectPath, setProjectPath] = useState("")
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set())
  const [selectedConfigs, setSelectedConfigs] = useState<Set<string>>(new Set())

  const handleScan = () => {
    const trimmed = projectPath.trim()
    if (!trimmed) return
    onScanPath(trimmed)
  }

  const handleDiscover = () => {
    onDiscover(projectPath.trim(), changeDescription)
  }

  const handleApprove = () => {
    onApprove(
      projectPath.trim(),
      Array.from(selectedFiles),
      selectedConfigs.size > 0 ? Array.from(selectedConfigs) : undefined
    )
  }

  const toggleFile = (path: string) => {
    setSelectedFiles((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const toggleConfig = (name: string) => {
    setSelectedConfigs((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const selectAll = () => {
    setSelectedFiles(new Set(discoveredFiles.map((f) => f.path)))
  }

  const selectNone = () => {
    setSelectedFiles(new Set())
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
        Point to an existing project so advisors can give file-level recommendations.
      </p>

      {/* Path input */}
      {!treeResult && (
        <div className="flex gap-2">
          <input
            type="text"
            value={projectPath}
            onChange={(e) => setProjectPath(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleScan() }}
            placeholder="/path/to/your/project"
            className="flex-1 px-3 py-2 rounded-lg border border-border
                       bg-surface text-sm text-text-primary font-mono
                       placeholder:text-text-muted
                       focus:outline-none focus:ring-2 focus:ring-accent/40"
            autoFocus
          />
          <button
            onClick={handleScan}
            disabled={!projectPath.trim() || isScanning}
            className="px-4 py-2 rounded-lg text-sm bg-accent text-white
                       hover:opacity-90 disabled:opacity-40
                       disabled:cursor-not-allowed transition-opacity"
          >
            {isScanning ? "Scanning..." : "Scan"}
          </button>
        </div>
      )}

      {/* Tree result */}
      {treeResult && (
        <div className="space-y-4">
          {/* Tech stack summary */}
          <div className="flex flex-wrap gap-2">
            {treeResult.tech_stack.languages.map((lang) => (
              <span key={lang} className="px-2 py-1 text-xs rounded bg-accent/10 text-accent">
                {lang}
              </span>
            ))}
            {treeResult.tech_stack.frameworks.map((fw) => (
              <span key={fw} className="px-2 py-1 text-xs rounded bg-green-500/10 text-green-600 dark:text-green-400">
                {fw}
              </span>
            ))}
          </div>

          {/* Directory tree */}
          <details className="border border-border rounded-lg">
            <summary className="px-4 py-2 text-sm text-text-secondary cursor-pointer
                                hover:bg-surface-secondary transition-colors">
              Directory tree
            </summary>
            <pre className="px-4 py-3 text-xs font-mono text-text-muted
                            max-h-48 overflow-auto bg-surface-tertiary">
              {treeResult.directory_tree}
            </pre>
          </details>

          {/* Config files */}
          {treeResult.config_files.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
                Config files to include
              </h4>
              <div className="flex flex-wrap gap-2">
                {treeResult.config_files.map((name) => (
                  <label
                    key={name}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                               text-xs border cursor-pointer transition-colors
                               ${selectedConfigs.has(name)
                                 ? "border-accent bg-accent/10 text-accent"
                                 : "border-border text-text-secondary hover:border-text-muted"}`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedConfigs.has(name)}
                      onChange={() => toggleConfig(name)}
                      className="sr-only"
                    />
                    <span className="font-mono">{name}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Discover button */}
          {discoveredFiles.length === 0 && (
            <button
              onClick={handleDiscover}
              disabled={isScanning}
              className="px-4 py-2 rounded-lg text-sm bg-accent text-white
                         hover:opacity-90 disabled:opacity-40
                         transition-opacity self-start"
            >
              {isScanning ? "Discovering..." : "Find relevant files"}
            </button>
          )}

          {/* Discovered files */}
          {discoveredFiles.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-semibold text-text-muted uppercase tracking-wide">
                  Relevant files ({discoveredFiles.length})
                </h4>
                <div className="flex gap-2">
                  <button onClick={selectAll} className="text-xs text-accent hover:underline">
                    Select all
                  </button>
                  <button onClick={selectNone} className="text-xs text-text-muted hover:underline">
                    Clear
                  </button>
                </div>
              </div>

              <div className="space-y-1 max-h-60 overflow-y-auto">
                {discoveredFiles.map((file) => (
                  <label
                    key={file.path}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg
                               text-sm cursor-pointer transition-colors
                               ${selectedFiles.has(file.path)
                                 ? "bg-accent/5 border border-accent/30"
                                 : "hover:bg-surface-secondary border border-transparent"}`}
                  >
                    <input
                      type="checkbox"
                      checked={selectedFiles.has(file.path)}
                      onChange={() => toggleFile(file.path)}
                      className="rounded border-border"
                    />
                    <span className="font-mono text-xs flex-1 text-text-secondary">
                      {file.path}
                    </span>
                    {file.is_sensitive && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 dark:text-amber-400">
                        sensitive
                      </span>
                    )}
                    <span className="text-xs text-text-muted">
                      {file.score.toFixed(1)}
                    </span>
                  </label>
                ))}
              </div>

              <button
                onClick={handleApprove}
                disabled={selectedFiles.size === 0 || isScanning}
                className="mt-3 px-5 py-2 rounded-lg text-sm font-medium
                           bg-accent text-white hover:opacity-90
                           disabled:opacity-40 disabled:cursor-not-allowed
                           transition-opacity"
              >
                {isScanning
                  ? "Reading files..."
                  : `Approve & continue (${selectedFiles.size} files)`}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
