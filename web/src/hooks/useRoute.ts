import { useCallback, useSyncExternalStore } from "react"

// ---------------------------------------------------------------------------
// Minimal History-API router (no library dependency)
//
// Only two URLs:  /  (council wizard)  and  /history  (plan list).
// Plan detail is handled by component state inside PlanHistory, not by URL.
// ---------------------------------------------------------------------------

type Listener = () => void
const listeners = new Set<Listener>()

function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function getSnapshot(): string {
  return window.location.pathname
}

function notify(): void {
  for (const listener of listeners) listener()
}

// Listen for browser back/forward
if (typeof window !== "undefined") {
  window.addEventListener("popstate", notify)
}

export function navigate(
  to: string,
  opts?: { replace?: boolean }
): void {
  if (window.location.pathname === to) return
  if (opts?.replace) {
    window.history.replaceState(null, "", to)
  } else {
    window.history.pushState(null, "", to)
  }
  notify()
}

// ---------------------------------------------------------------------------
// Route types
// ---------------------------------------------------------------------------

export type Route =
  | { view: "council" }
  | { view: "history" }

function parseRoute(pathname: string): Route {
  if (pathname === "/history") {
    return { view: "history" }
  }
  return { view: "council" }
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useRoute(): Route & { navigate: typeof navigate } {
  const pathname = useSyncExternalStore(subscribe, getSnapshot)
  const route = parseRoute(pathname)
  return { ...route, navigate }
}

export function useNavigate(): typeof navigate {
  return useCallback(
    (to: string, opts?: { replace?: boolean }) => navigate(to, opts),
    []
  )
}
