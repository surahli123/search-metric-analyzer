/**
 * DataQualityChecks.jsx
 *
 * A horizontal row of PASS/WARN pill badges summarizing data quality checks
 * that ran before the investigation. These give the reader confidence (or
 * appropriate skepticism) about the input data before they read the results.
 *
 * Think of it like a data pipeline health indicator — each badge is one check
 * (e.g. "Sample Size", "Day-of-Week Match") that either passed or needs attention.
 *
 * Props:
 *   checks {Array<{label: string, status: 'pass' | 'warn'}>}
 *     — Array of check objects. Each has a human-readable label and a status.
 *     — 'pass' → green PASS badge
 *     — 'warn' (or anything other than 'pass') → amber WARN badge
 *
 * Example:
 *   <DataQualityChecks checks={[
 *     { label: 'Sample Size', status: 'pass' },
 *     { label: 'Day-of-Week Match', status: 'warn' }
 *   ]} />
 */
export default function DataQualityChecks({ checks }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {checks.map((check) => {
        // Treat any non-'pass' status as a warning — makes the component defensive
        // against unexpected status strings from the backend
        const isPass = check.status === 'pass'
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
            {/* Status prefix followed by the check label */}
            {isPass ? 'PASS' : 'WARN'} {check.label}
          </span>
        )
      })}
    </div>
  )
}
