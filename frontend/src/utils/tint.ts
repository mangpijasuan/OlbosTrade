/**
 * Build a translucent tint from a colour that may be a CSS custom property.
 *
 * The obvious way to do this is string concatenation:
 *
 *     border: `1px solid ${tone}55`
 *
 * and it works only when `tone` is a literal hex. When it is a var() reference
 * — which is how this codebase carries its palette — it silently produces
 * nothing. var() substitutes at the TOKEN level, so `var(--amber)55` is two
 * tokens rather than an 8-digit colour, and the browser drops the whole
 * declaration.
 *
 * Verified in Chromium with `--amber: #f59e0b`:
 *
 *     var(--amber)55  → border-style "none", background rgba(0,0,0,0)  ← dropped
 *     #f59e0b55       → rgba(245,158,11,0.333)                        ← fine
 *     color-mix(…)    → works for both var() and hex                  ← this
 *
 * So the border or background does not merely come out faint; it is absent.
 * The failure is invisible in review because the concatenated form looks
 * obviously correct, and invisible in tests because jsdom does not parse it.
 *
 * color-mix handles both input shapes, which matters because the palette is
 * mid-migration between var() tokens and literals. Supported in Chrome 111+,
 * Safari 16.2+ and Firefox 113+ (all 2023).
 */

/**
 * @param color  Any CSS colour — "var(--amber)", "#f59e0b", "rgb(…)".
 * @param alpha  Opacity 0–1.
 */
export function tint(color: string, alpha: number): string {
  const pct = Math.round(Math.max(0, Math.min(1, alpha)) * 100);
  return `color-mix(in srgb, ${color} ${pct}%, transparent)`;
}

/** Common weights, named so call sites read as intent rather than arithmetic. */
export const TINT_BORDER = 0.4;   // a visible edge in the colour's hue
export const TINT_FILL = 0.08;    // a wash behind text, still legible
