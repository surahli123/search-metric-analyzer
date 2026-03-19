/**
 * DataQualityChecks.jsx
 *
 * A horizontal row of PASS/WARN pill badges summarizing data quality checks
 * that ran before the investigation. These give the reader confidence (or
 * appropriate skepticism) about the input data before they read the results.
 *
 * Think of it like a data pipeline health indicator — each badge is one check
 * (e.g. "Data integrity", "Coverage") that either passed or needs attention.
 *
 * Human-readable label mapping: technical labels from the backend are mapped
 * to friendlier names for non-technical readers. The technical label is shown
 * in parentheses for WARN status only (when engineers need to debug).
 *
 * Props:
 *   checks {Array<{label: string, status: 'pass' | 'warn'}>}
 *     — Array of check objects. Each has a human-readable label and a status.
 *     — 'pass' → green PASS badge
 *     — 'warn' (or anything other than 'pass') → amber WARN badge
 *
 * Example:
 *   <DataQualityChecks checks={[
 *     { label: 'Logging artifact', status: 'pass' },
 *     { label: 'Trust gate', status: 'warn' }
 *   ]} />
 */

// Maps technical backend labels to human-readable names.
// Technical labels are still useful for engineers debugging WARN states.
const HUMAN_LABELS = {
  'Logging artifact': 'Data integrity',
  'Decomposition completeness': 'Coverage',
  'Trust gate': 'Data quality',
}

export default function DataQualityChecks({ checks }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {checks.map((check) => {
        // Treat any non-'pass' status as a warning — makes the component defensive
        // against unexpected status strings from the backend
        const isPass = check.status === 'pass'

        // Use human-friendly label, fall back to original if no mapping exists
        const humanLabel = HUMAN_LABELS[check.label] || check.label

        // For WARN status, show the technical label in parentheses so engineers
        // can quickly identify what system produced the warning
        const displayLabel = !isPass && HUMAN_LABELS[check.label]
          ? `${humanLabel} (${check.label})`
          : humanLabel

        return (
          <span
            key={check.label}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium"
            style={{
              background: isPass ? 'var(--green-bg)' : 'var(--amber-bg)',
              color: isPass ? 'var(--green)' : 'var(--amber)',
              border: `1px solid ${isPass ? 'var(--green-border)' : 'var(--amber-border)'}`
            }}
          >
            {/* Status prefix followed by the display label */}
            {isPass ? 'PASS' : 'WARN'} {displayLabel}
          </span>
        )
      })}
    </div>
  )
}
