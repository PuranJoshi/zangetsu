import { useCallback, useState } from "react"
import type {
  DiscoveredFile,
  ProjectContext,
  ScanTreeResult,
} from "../types"

export type ScanPhase = "idle" | "scanning" | "discovering" | "approving" | "done" | "error"

export interface UseProjectScanResult {
  phase: ScanPhase
  treeResult: ScanTreeResult | null
  discoveredFiles: DiscoveredFile[]
  projectContext: ProjectContext | null
  error: string | null
  scanTree: (projectPath: string) => Promise<void>
  discoverFiles: (projectPath: string, changeDescription: string) => Promise<void>
  approveFiles: (
    projectPath: string,
    approvedPaths: string[],
    configFiles?: string[]
  ) => Promise<void>
  reset: () => void
}

export function useProjectScan(): UseProjectScanResult {
  const [phase, setPhase] = useState<ScanPhase>("idle")
  const [treeResult, setTreeResult] = useState<ScanTreeResult | null>(null)
  const [discoveredFiles, setDiscoveredFiles] = useState<DiscoveredFile[]>([])
  const [projectContext, setProjectContext] = useState<ProjectContext | null>(null)
  const [error, setError] = useState<string | null>(null)

  const scanTree = useCallback(async (projectPath: string) => {
    setPhase("scanning")
    setError(null)
    try {
      const res = await fetch("/api/scan/tree", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_path: projectPath }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data: ScanTreeResult = await res.json()
      setTreeResult(data)
      setPhase("discovering")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scan failed")
      setPhase("error")
    }
  }, [])

  const discoverFiles = useCallback(
    async (projectPath: string, changeDescription: string) => {
      setPhase("discovering")
      setError(null)
      try {
        const res = await fetch("/api/scan/discover", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_path: projectPath,
            change_description: changeDescription,
          }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || `HTTP ${res.status}`)
        }
        const data = await res.json()
        setDiscoveredFiles(data.discovered_files || [])
        setPhase("approving")
      } catch (err) {
        setError(err instanceof Error ? err.message : "Discovery failed")
        setPhase("error")
      }
    },
    []
  )

  const approveFiles = useCallback(
    async (
      projectPath: string,
      approvedPaths: string[],
      configFiles?: string[]
    ) => {
      setPhase("approving")
      setError(null)
      try {
        const res = await fetch("/api/scan/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_path: projectPath,
            approved_paths: approvedPaths,
            config_files: configFiles,
          }),
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          throw new Error(err.detail || `HTTP ${res.status}`)
        }
        const data = await res.json()
        setProjectContext(data.project_context)
        setPhase("done")
      } catch (err) {
        setError(err instanceof Error ? err.message : "Approval failed")
        setPhase("error")
      }
    },
    []
  )

  const reset = useCallback(() => {
    setPhase("idle")
    setTreeResult(null)
    setDiscoveredFiles([])
    setProjectContext(null)
    setError(null)
  }, [])

  return {
    phase,
    treeResult,
    discoveredFiles,
    projectContext,
    error,
    scanTree,
    discoverFiles,
    approveFiles,
    reset,
  }
}
