// ---------------------------------------------------------------------------
// Pipeline stages
// ---------------------------------------------------------------------------

export type SessionStage =
  | "idle"
  | "framing"
  | "confirming"
  | "scanning"
  | "advising"
  | "analyzing"    // Pass 1: conflict analysis before synthesis
  | "synthesizing"
  | "reviewing"    // re-advise in progress (user stays on plan view)
  | "completed"
  | "error"

// ---------------------------------------------------------------------------
// Framer protocol (WebSocket)
// ---------------------------------------------------------------------------

export type FramerStatus =
  | "idle"
  | "connecting"
  | "thinking"
  | "chatting"
  | "done"
  | "error"

export interface FramerMessage {
  role: "user" | "framer"
  text: string
  choices?: string[]
  msgId?: string
}

// ---------------------------------------------------------------------------
// Framed requirement (mirrors Python FramedRequirement)
// ---------------------------------------------------------------------------

export interface FramedRequirement {
  type: string
  title: string
  description: string
  acceptance_criteria: string[]
  out_of_scope: string[]
  assumptions: string[]
  clarifications_needed: string[]
  stories: FramedRequirement[]
}

// ---------------------------------------------------------------------------
// Project scanning
// ---------------------------------------------------------------------------

export interface TechStack {
  languages: string[]
  frameworks: string[]
  build_tools: string[]
  package_manager: string
  runtime: string
}

export interface TestPatterns {
  test_framework: string
  test_directories: string[]
  test_file_pattern: string
  example_test_files: string[]
}

export interface DiscoveredFile {
  path: string
  score: number
  is_sensitive: boolean
}

export interface ScanTreeResult {
  project_path: string
  directory_tree: string
  tech_stack: TechStack
  test_patterns: TestPatterns
  config_files: string[]
}

export interface ProjectContext {
  project_path: string
  directory_tree: string
  tech_stack: TechStack
  config_files: Record<string, string>
  relevant_files: Record<string, string>
  test_patterns: TestPatterns
  summary: string
  code_comments: Record<string, string[]>
}

// ---------------------------------------------------------------------------
// Advisor config (display metadata for the 7 advisors)
// ---------------------------------------------------------------------------

export interface AdvisorDisplayConfig {
  color: string
  icon: string
  shortDesc: string
}

export const ADVISOR_CONFIG: Record<string, AdvisorDisplayConfig> = {
  "Executor Advisor":  { color: "#f97316", icon: "\u26A1", shortDesc: "How to build it" },
  "Security Advisor":  { color: "#ef4444", icon: "\uD83D\uDEE1", shortDesc: "Vulnerabilities & auth" },
  "Quality Advisor":   { color: "#22c55e", icon: "\u2713", shortDesc: "Testability & DX" },
  "Business Advisor":  { color: "#3b82f6", icon: "\uD83D\uDCCA", shortDesc: "Value & scope" },
  "Architect Advisor": { color: "#a855f7", icon: "\uD83C\uDFD7", shortDesc: "Structure & patterns" },
  "Risk Advisor":      { color: "#eab308", icon: "\u26A0", shortDesc: "What could break" },
  "Fraud Advisor":     { color: "#dc2626", icon: "\uD83D\uDD0D", shortDesc: "Loopholes & abuse" },
}

// ---------------------------------------------------------------------------
// Advisor response
// ---------------------------------------------------------------------------

export interface AdvisorResponse {
  name: string
  response: string
}

// ---------------------------------------------------------------------------
// Implementation plan (mirrors Python ChangePlan)
// ---------------------------------------------------------------------------

export interface ImplementationStep {
  order: number
  file_path: string
  action: string
  description: string
  depends_on: number[]
  story: string
}

export interface IncrementalChange {
  type: string          // "story" | "task" | "bug"
  title: string
  description: string
  acceptance_criteria: string[]
  steps: number[]       // implementation_step order numbers
}

export interface ChangePlan {
  plan_id: string
  title: string
  summary: string
  change_description: string
  affected_files: string[]
  implementation_steps: ImplementationStep[]
  incremental_changes: IncrementalChange[]
  architecture_notes: string
  security_notes: string
  quality_notes: string
  risk_assessment: string
  execution_strategy: string
  acceptance_criteria: string[]
  estimated_effort: string
  risk_level: string
  negotiation_round: number
  raw_advisor_responses: Record<string, string>
  base_plan_id?: string | null
}

// ---------------------------------------------------------------------------
// Token usage tracking
// ---------------------------------------------------------------------------

export interface TokenUsageData {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface StageTokenUsage {
  stage: string
  usage: TokenUsageData
}

export interface TokenUsageState {
  stages: StageTokenUsage[]
  total: TokenUsageData
}

/**
 * Convert a backend token_usage dict (from TokenTracker.to_dict()) to the
 * frontend TokenUsageState format.  Returns null if the input is missing
 * or malformed.
 *
 * Backend format:  { stages: { name: { prompt_tokens, ... }, ... }, total: { ... } }
 * Frontend format: { stages: [{ stage, usage }, ...], total: { ... } }
 */
export function tokenUsageDictToState(
  data: Record<string, unknown> | null | undefined,
): TokenUsageState | null {
  if (!data) return null
  const stagesDict = data.stages as Record<string, TokenUsageData> | undefined
  const total = data.total as TokenUsageData | undefined
  if (!stagesDict || !total) return null

  const stages: StageTokenUsage[] = Object.entries(stagesDict).map(
    ([name, usage]) => ({ stage: name, usage }),
  )
  return { stages, total }
}

// ---------------------------------------------------------------------------
// Session state (used by useCouncilStream)
// ---------------------------------------------------------------------------

export interface CouncilSession {
  stage: SessionStage
  planId: string | null
  advisorNames: string[]
  advisorResponses: AdvisorResponse[]
  plan: ChangePlan | null
  duration: number | null
  error: string | null
  tokenUsage: TokenUsageState | null
}

export function initialSession(): CouncilSession {
  return {
    stage: "idle",
    planId: null,
    advisorNames: [],
    advisorResponses: [],
    plan: null,
    duration: null,
    error: null,
    tokenUsage: null,
  }
}

// ---------------------------------------------------------------------------
// Plan list (from /plans endpoint)
// ---------------------------------------------------------------------------

export interface PlanSummary {
  plan_id: string
  timestamp: string
  change_description: string
  status: string
  risk_level: string
  effort: string
  base_plan_id?: string | null
}

export interface TranscriptSummary {
  plan_id: string
  timestamp: string
  question: string
  status: string
  base_plan_id?: string | null
  has_framed_question: boolean
  message_count: number
}

// ---------------------------------------------------------------------------
// Council feedback (advisor plan review + decision gate)
// ---------------------------------------------------------------------------

export interface AdvisorReview {
  name: string
  review: string
}

export interface RecommendationDecision {
  advisor: string
  recommendation: string
  priority: "HIGH" | "MEDIUM" | "LOW"
  decision: "ACCEPT" | "DEFER" | "DROP"
  reason: string
}

export interface CouncilDecision {
  verdict: "PROCEED" | "REVISE"
  rationale: string
  decisions: RecommendationDecision[]
  accepted_changes_summary: string
}

export type CouncilFeedbackStage =
  | "idle"
  | "reviewing"
  | "deciding"
  | "completed"
  | "error"

export interface CouncilFeedbackState {
  stage: CouncilFeedbackStage
  advisorReviews: AdvisorReview[]
  decision: CouncilDecision | null
  error: string | null
  tokenUsage: TokenUsageState | null
}
