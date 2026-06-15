import { useCallback, useEffect, useRef, useState } from "react"
import type { FramerMessage, FramerStatus, FramedRequirement } from "../types"

export interface UseFramerResult {
  messages: FramerMessage[]
  status: FramerStatus
  framedRequirement: FramedRequirement | null
  requestId: string | null
  /** plan_id returned by the server (transcript was created with this ID). */
  planId: string | null
  error: string | null
  startFraming: (question: string, planId?: string) => void
  sendReply: (text: string) => void
  skipFraming: () => void
}

export function useFramer(): UseFramerResult {
  const [messages, setMessages] = useState<FramerMessage[]>([])
  const [status, setStatus] = useState<FramerStatus>("idle")
  const [framedRequirement, setFramedRequirement] =
    useState<FramedRequirement | null>(null)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [planId, setPlanId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pendingMsgIdRef = useRef<string | null>(null)
  const messagesRef = useRef<FramerMessage[]>([])
  const statusRef = useRef<FramerStatus>("idle")

  // Keep refs in sync with state for use inside callbacks
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])
  useEffect(() => {
    statusRef.current = status
  }, [status])

  const startFraming = useCallback((question: string, existingPlanId?: string) => {
    // Close any existing connection
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setMessages([{ role: "user", text: question }])
    setStatus("connecting")
    setFramedRequirement(null)
    setRequestId(null)
    setPlanId(null)
    setError(null)

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:"
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/framer`)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus("thinking")
      const msg: Record<string, string> = { type: "question", text: question }
      if (existingPlanId) msg.plan_id = existingPlanId
      ws.send(JSON.stringify(msg))
    }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)

      switch (data.type) {
        case "framer_question":
          pendingMsgIdRef.current = data.msg_id
          if (data.plan_id) setPlanId(data.plan_id)
          setMessages((prev) => [
            ...prev,
            {
              role: "framer",
              text: data.question,
              choices: data.choices,
              msgId: data.msg_id,
            },
          ])
          setStatus("chatting")
          break

        case "framed":
          setFramedRequirement(data.framed_requirement)
          setRequestId(data.request_id)
          if (data.plan_id) setPlanId(data.plan_id)
          setStatus("done")
          break

        case "error":
          setError(data.message)
          setStatus("error")
          break

        case "history":
          // Resume support -- replay prior messages
          if (data.messages) {
            setMessages(data.messages)
          }
          break
      }
    }

    ws.onclose = () => {
      wsRef.current = null
      setStatus((prev) =>
        prev === "done" || prev === "error" ? prev : "error"
      )
    }

    ws.onerror = () => {
      setError("WebSocket connection failed")
      setStatus("error")
    }
  }, [])

  const sendReply = useCallback((text: string) => {
    if (!wsRef.current || !pendingMsgIdRef.current) return

    setMessages((prev) => [...prev, { role: "user", text }])
    setStatus("thinking")

    wsRef.current.send(
      JSON.stringify({
        type: "reply",
        text,
        msg_id: pendingMsgIdRef.current,
      })
    )
  }, [])

  const skipFraming = useCallback(() => {
    if (!wsRef.current) return

    // If still in "thinking" (LLM hasn't responded yet), the server
    // can't read the skip message because it's blocked on the LLM call.
    // Close the WebSocket and produce a fallback framed requirement
    // client-side from the original user message.
    const currentMessages = messagesRef.current
    const userMsg = currentMessages.find((m) => m.role === "user")

    if (statusRef.current === "thinking" || statusRef.current === "connecting") {
      wsRef.current.close()
      wsRef.current = null
      const title = (userMsg?.text || "").slice(0, 80) || "Plan"
      setFramedRequirement({
        type: "story",
        title,
        description: userMsg?.text || "",
        acceptance_criteria: [],
        out_of_scope: [],
        assumptions: [],
        clarifications_needed: [],
        stories: [],
      })
      setStatus("done")
      return
    }

    // If in "chatting" (question already asked), send skip to the server
    // so it can force-frame with the gathered context.
    setStatus("thinking")
    wsRef.current.send(JSON.stringify({ type: "skip" }))
  }, [])

  return {
    messages,
    status,
    framedRequirement,
    requestId,
    planId,
    error,
    startFraming,
    sendReply,
    skipFraming,
  }
}
