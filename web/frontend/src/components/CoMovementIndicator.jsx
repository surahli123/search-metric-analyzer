/**
 * CoMovementIndicator.jsx
 *
 * Displays the directional movement of the 4 core search metrics alongside
 * the matched co-movement pattern name and description.
 *
 * Co-movement is the key diagnostic signal — looking at how metrics move
 * TOGETHER (not in isolation) narrows hypotheses dramatically. This component
 * makes that pattern immediately readable at a glance.
 *
 * Special case — is_positive=true (AI Adoption pattern):
 *   When all metric movement is "expected by design" (e.g. AI answers up, clicks down),
 *   arrow colors switch from red/green to neutral blue. An "Expected" badge is prepended
 *   to the pattern description to prevent misreading as a regression.
 *
 * Props:
 *   coMovement {object}
 *     pattern_matched     {string}  — ID of the matched pattern, e.g. "ai_adoption"
 *     is_positive         {boolean} — True when co-movement is expected/positive
 *     metric_directions   {object}  — Keyed by metric name, each value: { direction, delta_pct }
 *                                     direction: 'up' | 'down' | 'stable'
 *                                     delta_pct: number (positive or negative)
 *     pattern_description {string}  — Human-readable explanation of the matched pattern
 */

// Unicode arrows for the three direction states
const ARROWS = { up: '↑', down: '↓', stable: '→' }

// Maps internal metric keys to display labels
const METRIC_LABELS = {
  click_quality: 'Click Quality',
  search_quality_success: 'SQS',
  ai_trigger: 'AI Trigger',
  ai_success: 'AI Success'
}

export default function CoMovementIndicator({ coMovement }) {
  const { metric_directions, pattern_description, is_positive } = coMovement

  return (
    <div className="p-4 rounded-lg border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', fontFamily: "'Fira Sans', sans-serif" }}>
      {/* Metric direction row — one chip per metric */}
      <div className="flex gap-4 mb-3 flex-wrap">
        {Object.entries(metric_directions).map(([key, { direction, delta_pct }]) => (
          <div key={key} className="flex items-center gap-1.5">
            <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
              {METRIC_LABELS[key] || key}
            </span>
            <span
              className="text-sm font-semibold"
              style={{
                // When is_positive, use neutral blue for ALL arrows — avoids misreading
                // red "↓ Click Quality" as a problem when it's actually expected AI adoption behavior
                color: is_positive
                  ? 'var(--accent)'
                  : direction === 'up'
                    ? 'var(--green)'
                    : direction === 'down'
                      ? 'var(--red)'
                      : 'var(--text-muted)'
              }}
            >
              {ARROWS[direction] || '?'} {delta_pct > 0 ? '+' : ''}{delta_pct}%
            </span>
          </div>
        ))}
      </div>

      {/* Pattern description row — "Expected" badge prepended for positive patterns */}
      <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        {is_positive && (
          <span
            className="inline-block px-2 py-0.5 rounded text-xs font-semibold mr-2"
            style={{ background: 'var(--accent-light)', color: 'var(--accent)' }}
          >
            Expected
          </span>
        )}
        {pattern_description}
      </div>
    </div>
  )
}
