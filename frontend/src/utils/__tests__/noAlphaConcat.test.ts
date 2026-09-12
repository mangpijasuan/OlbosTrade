/**
 * No colour in this codebase may be built by adjoining a two-hex-digit alpha
 * to another value. Use tint().
 *
 * This is the actual deliverable of the tint work. Fixing the sites was the
 * easy half; the hard half is that they stay fixed, because the broken form is
 * invisible to everything that normally catches bugs:
 *
 *   - it reads as obviously correct
 *   - jsdom parses it happily, so component tests pass
 *   - TypeScript sees a valid string
 *   - the linter has no opinion
 *   - the browser drops the declaration SILENTLY: no console warning, the
 *     border simply is not painted
 *
 * The sweep that produced this rule found the pattern in SIX different
 * spellings, and the first four passes each missed some. That history is why
 * this scans source text rather than trying to be clever:
 *
 *   1.  `1px solid ${tone}55`                  template interpolation
 *   2.  "1px solid var(--cyan)30"              inline literal
 *   3.  color + "60"                           string concatenation
 *   4.  `${cond ? "var(--red)" : "var(--amber)"}60`   expression, not an identifier
 *   5.  `${LIFECYCLE_COLOR[state]}60`          index / call expression
 *   6.  `${color}${muted ? "55" : "88"}`       the ALPHA itself interpolated
 *
 * A grep-style test is a blunt instrument and will occasionally want an
 * exemption. Add one deliberately, with a reason, rather than loosening the
 * pattern — a loosened pattern is how spellings 3 to 6 survived the first
 * sweep.
 */

import { describe, expect, it } from "vitest";

/**
 * Sources read through Vite's own glob rather than node:fs, so this needs no
 * @types/node and stays honest about what ships: the same resolver the bundler
 * uses decides what counts as source.
 */
const FILES = import.meta.glob("/src/**/*.{ts,tsx}", {
  query: "?raw", eager: true, import: "default",
}) as Record<string, string>;

/** Files allowed to contain the pattern, each for a stated reason. */
const EXEMPT = [
  "/src/utils/tint.ts",                             // documents the broken form
  "/src/utils/__tests__/tint.test.ts",              // asserts against it
  "/src/utils/__tests__/noAlphaConcat.test.ts",     // this file
];

const PATTERNS: Array<[RegExp, string]> = [
  [/\$\{[^{}]*\}[0-9a-fA-F]{2}\b/, "alpha appended to an interpolation"],
  [/\+\s*["'][0-9a-fA-F]{2}["']/, "alpha appended by string concatenation"],
  [/var\(--[a-z-]+\)[0-9a-fA-F]{2}/, "alpha appended to a literal var()"],
  [/\$\{[^{}]*\}\$\{[^{}]*["'][0-9a-fA-F]{2}["']/, "interpolated alpha"],
];

describe("no alpha-concatenated colours", () => {
  it("finds none anywhere in src/", () => {
    const offenders: string[] = [];

    for (const [file, source] of Object.entries(FILES)) {
      if (EXEMPT.includes(file)) continue;

      source.split("\n").forEach((line: string, i: number) => {
        const code = line.trim();
        // Prose describing the bug is not the bug.
        if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*")) return;
        for (const [pattern, label] of PATTERNS) {
          if (pattern.test(line)) {
            offenders.push(`${file}:${i + 1}  [${label}]\n      ${code.slice(0, 100)}`);
          }
        }
      });
    }

    expect(
      offenders,
      "Colours built by adjoining an alpha are dropped by the browser — the " +
      "declaration does not render at all. Use tint(color, alpha) from " +
      "utils/tint.\n\n" + offenders.join("\n")
    ).toEqual([]);
  });

  it("would actually catch a regression", () => {
    // A guard test that cannot fail is decoration. This proves each pattern
    // matches the shape it is meant to reject.
    const samples = [
      "border: `1px solid ${tone}55`,",
      'border: "1px solid var(--cyan)30",',
      'border: `1px solid ${isBest ? color + "60" : "none"}`,',
      'border: `1px solid ${LIFECYCLE_COLOR[s]}60`,',
      'border: `1px solid ${color}${muted ? "55" : "88"}`,',
    ];
    for (const s of samples) {
      expect(
        PATTERNS.some(([p]) => p.test(s)),
        `no pattern caught: ${s}`
      ).toBe(true);
    }
  });

  it("does not flag legitimate colour code", () => {
    // Guards against the opposite failure: a rule so broad it forces people to
    // work around it, which ends with the rule being deleted.
    const fine = [
      "border: `1px solid ${tint(color, 0.4)}`,",
      'background: "var(--bg-3)",',
      "color: tone,",
      "const AMBER = \"#f59e0b\";",
      "padding: `${gap}px`,",
      "gridTemplate: `${rows}fr`,",
    ];
    for (const s of fine) {
      expect(
        PATTERNS.some(([p]) => p.test(s)),
        `false positive on: ${s}`
      ).toBe(false);
    }
  });
});
