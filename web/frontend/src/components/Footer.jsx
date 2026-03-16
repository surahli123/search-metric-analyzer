// Footer.jsx — persistent footer strip with verdict badge + summary + metadata.
//
// WHY a footer: the verdict from VerdictStrip is at the top; the footer echoes it
// at the bottom so users who scrolled through the full report can see the conclusion
// without scrolling back up. This is a common pattern in long-form reports.
//
// Color logic mirrors VerdictStrip exactly — same three states:
//   - isPositive (AI adoption expected pattern): accent blue
//   - P0/P1 (real regression): red
//   - Otherwise (P2, within variance): green

export default function Footer({ verdict, summary, totalQueries, dateRange, isPositive, severity }) {
  // Determine badge colors using the same three-state logic as VerdictStrip
  let badgeBg, badgeColor
  if (isPositive) {
    // Positive signal (e.g., AI adoption causing expected click drop) — use blue
    badgeBg = 'var(--accent-light)'
    badgeColor = 'var(--accent)'
  } else if (severity === 'P0' || severity === 'P1') {
    // Real regression — use red to signal action required
    badgeBg = 'var(--red-bg)'
    badgeColor = 'var(--red)'
  } else {
    // P2 or within variance — use green to signal normal / no action needed
    badgeBg = 'var(--green-bg)'
    badgeColor = 'var(--green)'
  }

  return (
    <div
      className="flex items-center justify-between px-6 py-3 border-t"
      style={{
        background: 'var(--bg-card)',
        borderColor: 'var(--border)',
        fontFamily: "'Fira Sans', sans-serif",
      }}
    >
      {/* Left side: verdict badge + human-readable summary */}
      <div className="flex items-center gap-3">
        <span
          className="text-xs font-semibold px-2.5 py-1 rounded"
          style={{ background: badgeBg, color: badgeColor }}
        >
          {verdict}
        </span>
        <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          {summary}
        </span>
      </div>

      {/* Right side: query count + date range — contextual metadata */}
      <div className="flex items-center gap-4 text-xs" style={{ color: 'var(--text-muted)' }}>
        <span>{totalQueries}</span>
        <span>{dateRange}</span>
      </div>
    </div>
  )
}
