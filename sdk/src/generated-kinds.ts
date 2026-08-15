// AUTO-GENERATED from orchestrator/events/schemas.py — do not edit manually
// Run: node scripts/generate-types.mjs

export type EventKind =
  | "token"
  | "thought"
  | "tool_call"
  | "tool_result"
  | "step_start"
  | "step_end"
  | "checkpoint"
  | "error"
  | "done"
  | "cancelled";
