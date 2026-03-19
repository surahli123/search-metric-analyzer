// TraceStep.jsx — single step row in the pipeline execution trace.
//
// WHY this component exists: Each step in the diagnostic pipeline (SQL query,
// knowledge lookup, reasoning, output) needs a consistent visual representation.
// The type badge provides instant visual scanning — purple for SQL, teal for
// knowledge, coral for reasoning, green for output — so engineers can quickly
// spot which parts of the pipeline ran and what they produced.
//
// WHY type badges use CSS variables: The design system defines semantic colors
// in tokens.css (--purple, --teal, --coral, --green). Using variables instead
// of hardcoded hex values means the entire trace view updates if tokens change.
//
// Props:
//   step {object} — A single step from the phase's steps array:
//     - type      {string}  — 'sql' | 'knowledge' | 'reasoning' | 'output'
//     - label     {string}  — Short description (e.g., "Data quality gate")
//     - detail    {string}  — Longer explanation of what happened
//     - duration_s {number} — Optional: execution time (mainly for SQL steps)
//     - rows      {number}  — Optional: row count returned (SQL steps only)
//     - file      {string}  — Optional: knowledge file referenced

// Badge color mapping — maps step type to CSS variable pairs (bg + text).
// This lookup avoids a chain of if/else and makes it trivial to add new types.
const BADGE_COLORS = {
  sql:       { bg: 'var(--purple-bg)', color: 'var(--purple)' },
  knowledge: { bg: 'var(--teal-bg)',   color: 'var(--teal)' },
  reasoning: { bg: 'var(--coral-bg)',  color: 'var(--coral)' },
  output:    { bg: 'var(--green-bg)',  color: 'var(--green)' },
}

export default function TraceStep({ step }) {
  const { type, label, detail, duration_s, rows, file } = step
  const badgeStyle = BADGE_COLORS[type] || BADGE_COLORS.output

  // Build optional metadata string — only SQL steps typically have duration+rows,
  // but we show duration for any step that has it, and file for knowledge steps.
  const metaParts = []
  if (duration_s !== undefined && duration_s !== null) {
    metaParts.push(`${duration_s}s`)
  }
  if (rows !== undefined && rows !== null) {
    metaParts.push(`${rows} rows`)
  }
  if (file) {
    metaParts.push(file)
  }

  return (
    <div
      className="flex items-start gap-3 px-3 py-2 rounded"
      style={{ background: 'var(--bg-elevated)' }}
    >
      {/* Type badge — color-coded pill for quick visual scanning */}
      <span
        className="inline-block text-xs font-medium px-2 py-0.5 rounded whitespace-nowrap"
        style={{
          background: badgeStyle.bg,
          color: badgeStyle.color,
          fontFamily: "'Fira Code', monospace",
          fontSize: '11px',
          // Keep badge vertically aligned with the first line of label text
          marginTop: '2px',
        }}
      >
        {type}
      </span>

      {/* Content area — label + detail + optional metadata */}
      <div className="flex-1 min-w-0">
        {/* Label: the step's short name */}
        <div
          className="text-sm font-medium"
          style={{ color: 'var(--text-primary)', fontFamily: "'Fira Sans', sans-serif" }}
        >
          {label}
        </div>

        {/* Detail: longer explanation of what the step did */}
        <div
          className="text-xs mt-0.5"
          style={{ color: 'var(--text-secondary)', fontFamily: "'Fira Sans', sans-serif" }}
        >
          {detail}
        </div>

        {/* Optional metadata: duration, row count, file reference */}
        {metaParts.length > 0 && (
          <div
            className="text-xs mt-1"
            style={{
              color: 'var(--text-muted)',
              fontFamily: "'Fira Code', monospace",
              fontSize: '11px',
            }}
          >
            {metaParts.join(' / ')}
          </div>
        )}
      </div>
    </div>
  )
}
