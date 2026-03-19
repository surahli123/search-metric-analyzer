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
 *   verdict       {string}  — Short technical verdict label, e.g. "Ranking Regression Confirmed"
 *   verdictHuman  {string}  — Human-readable verdict, e.g. "Normal fluctuation — no action needed"
 *   detail        {string}  — One-sentence elaboration shown right after the verdict
 *   n             {string}  — Badge text, typically a query count or data window, e.g. "n=14,200 queries"
 *   isPositive    {boolean} — True when the movement is expected/positive (AI adoption pattern)
 *   severity      {string}  — 'P0' | 'P1' | 'P2' — controls red vs green when not positive
 *   severityHuman {string}  — Human-readable severity, e.g. "Minor" or "Urgent"
 */
export default function VerdictStrip({ verdict, verdictHuman, detail, n, isPositive, severity, severityHuman }) {
  // Derive display tokens from the two dimensions: isPositive + severity
  let bg, dotColor
  if (isPositive) {
    // Expected positive pattern — use brand blue to signal "this is working as designed"
    bg = 'var(--accent-light)'; dotColor = 'var(--accent)'
  } else if (severity === 'P0' || severity === 'P1') {
    // Real regression — red to signal action required
    bg = 'var(--red-bg)'; dotColor = 'var(--red)'
  } else {
    // P2 or below — within variance, green to signal no action needed
    bg = 'var(--green-bg)'; dotColor = 'var(--green)'
  }

  // Build combined severity display: "Minor (P2)" or "Urgent (P1)"
  // Falls back to just the technical severity if no human label provided
  const severityDisplay = severityHuman
    ? `${severityHuman} (${severity})`
    : severity

  return (
    <div
      className="flex items-center justify-between px-4 py-3 rounded-lg"
      style={{ background: bg, fontFamily: "'Fira Sans', sans-serif" }}
    >
      <div className="flex items-center gap-2 flex-wrap">
        {/* Colored dot acts as a quick-scan severity indicator */}
        <span className="inline-block w-2 h-2 rounded-full flex-shrink-0" style={{ background: dotColor }} />

        {/* Primary: human-readable verdict (shown large and bold) */}
        <span className="font-semibold" style={{ color: 'var(--text-primary)' }}>
          {verdictHuman || verdict}
        </span>

        {/* Severity badge — combines human + technical labels */}
        <span
          className="text-xs px-1.5 py-0.5 rounded font-medium"
          style={{ background: dotColor, color: 'white', opacity: 0.85 }}
        >
          {severityDisplay}
        </span>

        {/* Subtitle: technical verdict + metric detail for power users */}
        {verdictHuman && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {verdict}{detail}
          </span>
        )}

        {/* Fallback: show detail inline when no human verdict exists */}
        {!verdictHuman && (
          <span style={{ color: 'var(--text-secondary)' }}>{detail}</span>
        )}
      </div>

      {/* n badge — monospace so query counts read cleanly */}
      <span
        className="text-xs px-2 py-0.5 rounded flex-shrink-0"
        style={{ background: 'var(--bg-input)', color: 'var(--text-muted)', fontFamily: "'Fira Code', monospace" }}
      >
        {n}
      </span>
    </div>
  )
}
