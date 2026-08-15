#!/usr/bin/env node
/**
 * Generate TypeScript event types from the server's EventKind enum.
 *
 * This reads the Python source and generates the TypeScript event union.
 * Event types are generated, never hand-maintained — drift is a runtime failure.
 *
 * Usage: node scripts/generate-types.mjs
 */

import { readFileSync, writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectRoot = join(__dirname, "..", "..");

// Read the Python enum
const pythonSource = readFileSync(
  join(projectRoot, "orchestrator", "events", "schemas.py"),
  "utf-8"
);

// Extract enum values
const enumMatch = pythonSource.match(
  /class EventKind\(str, Enum\):([\s\S]*?)(?=\n\nclass|\n\n[A-Z])/
);
if (!enumMatch) {
  console.error("Could not find EventKind enum in schemas.py");
  process.exit(1);
}

const enumBody = enumMatch[1];
const kinds = [];
for (const line of enumBody.split("\n")) {
  const match = line.trim().match(/^(\w+)\s*=\s*"(\w+)"/);
  if (match) {
    kinds.push(match[2]);
  }
}

console.log(`Found ${kinds.length} event kinds: ${kinds.join(", ")}`);

// Generate the TypeScript union type
const typeUnion = kinds.map((k) => `  | "${k}"`).join("\n");
const output = `// AUTO-GENERATED from orchestrator/events/schemas.py — do not edit manually
// Run: node scripts/generate-types.mjs

export type EventKind =
${typeUnion};
`;

writeFileSync(join(__dirname, "..", "src", "generated-kinds.ts"), output);
console.log("Generated src/generated-kinds.ts");
