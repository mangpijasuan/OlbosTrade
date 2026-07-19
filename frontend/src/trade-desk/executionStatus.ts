/**
 * Map execution_events payloads to desk lifecycle labels.
 * Honest: no broker ack/partial/cancel entity yet — derived from result strings.
 */

export type DeskLifecycle =
  | "pending_approval"
  | "submitted"
  | "blocked"
  | "skipped"
  | "rejected"
  | "error"
  | "unknown";

export function lifecycleFromExecution(entry: {
  result?: string;
  status?: string;
}): DeskLifecycle {
  const r = (entry.result || entry.status || "").toLowerCase();
  if (r === "pending_approval" || r === "pending") return "pending_approval";
  if (r === "submitted" || r === "filled" || r === "partial") return "submitted";
  if (r === "blocked" || r.startsWith("order_")) return "blocked";
  if (r === "skipped") return "skipped";
  if (r === "rejected") return "rejected";
  if (r === "error") return "error";
  return "unknown";
}

export function lifecycleLabel(s: DeskLifecycle): string {
  switch (s) {
    case "pending_approval":
      return "PENDING";
    case "submitted":
      return "SUBMITTED";
    case "blocked":
      return "BLOCKED";
    case "skipped":
      return "SKIPPED";
    case "rejected":
      return "REJECTED";
    case "error":
      return "ERROR";
    default:
      return "—";
  }
}

export function lifecycleColor(s: DeskLifecycle): string {
  switch (s) {
    case "pending_approval":
      return "var(--orange)";
    case "submitted":
      return "var(--green)";
    case "blocked":
    case "error":
      return "var(--red)";
    case "skipped":
      return "var(--amber)";
    case "rejected":
      return "var(--ink-dim)";
    default:
      return "var(--ink-faint)";
  }
}
