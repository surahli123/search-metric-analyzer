/**
 * VerdictStrip.jsx
 *
 * A single-line TL;DR verdict banner shown at the top of an investigation result.
 * Think of it as the "executive summary row" — one glance tells the reader
 * whether this is a regression, a false alarm, or a positive AI signal.
 *
 * Color logic (mirrors the severity ladder in metric_definitions.yaml):
 *   isPositive=true             → blue  (accent-light bg)  — AI adoption, expected co-movement
 *   isPositive=false + P0/P1   → red   (red-bg)            — real regression, needs action
 *   isPositive=false + P2/other → green (green-bg)          — within variance, no action needed
 *
 * Props:
 *   verdict    {string}  — Short verdict label, e.g. "Ranking Regression Confirmed"
 *   detail     {string}  — One-sentence elaboration shown right after the verdict
 *   n          {string}  — Badge text, typically a query count or data window, e.g. "n=14,200 queries"
 *   isPositive {boolean} — True when the movement is expected/positive (AI adoption pattern)
 *   severity   {string}  — 'P0' | 'P1' | 'P2' — controls red vs green when not positive
 */
export default function VerdictStrip({ verdict, detail, n, isPositive, severity }) {
  // Derive display tokens from the two dimensions: isPositive + severity
  let bg, dotColor, borderColor
  if (isPositive) {
    // Expected positive pattern — use brand blue to signal "this is working as designed"
    bg = 'var(--accent-light)'; dotColor = 'var(--accent)'; borderColor = 'var(--accent)'
  } else if (severity === 'P0' || severity === 'P1') {
    // Real regression — red to signal action required
    bg = 'var(--red-bg)'; dotColor = 'var(--red)'; borderColor = 'var(--red)'
  } else {
    // P2 or below — within variance, green to signal no action needed
    bg = 'var(--green-bg)'; dotColor = 'var(--green)'; borderColor = 'var(--green)'
  }

  return (
    <div className="flex items-center justify-between px-4 py-3 rounded-lg" style={{ background: bg, borderLeft: `4px solid ${borderColor}`, fontFamily: "'Fira Sans', sans-serif" }}>
      <div className="flex items-center gap-2">
        {/* Colored dot acts as a quick-scan severity indicator */}
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: dotColor }} />
        <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>{verdict}</span>
        <span style={{ color: 'var(--text-secondary)' }}>{detail}</span>
      </div>
      {/* n badge — monospace so query counts read cleanly */}
      <span className="text-xs px-2 py-0.5 rounded" style={{ background: 'var(--bg-input)', color: 'var(--text-muted)', fontFamily: "'Fira Code', monospace" }}>{n}</span>
    </div>
  )
}
