/**
 * HypothesisChecklist — ordered hypothesis evaluation list with progressive disclosure.
 *
 * Matched hypotheses are shown prominently at the top as highlighted findings.
 * Remaining "not_evaluated" hypotheses are collapsed behind an expand toggle
 * to reduce visual noise — most readers only care about what WAS found.
 *
 * Props: hypotheses (array of {category, status, reason?})
 */
import { useState } from 'react'

const CATEGORY_LABELS = {
  instrumentation: 'Instrumentation / logging anomaly',
  connector: 'Connector / data pipeline change',
  query_understanding: 'Query understanding regression',
  algorithm_model: 'Algorithm / model change',
  experiment: 'Experiment ramp / de-ramp',
  ai_feature: 'AI feature effect',
  seasonal: 'Seasonal / external',
  user_behavior: 'User behavior shift',
}

export default function HypothesisChecklist({ hypotheses }) {
  // Separate matched from non-matched for progressive disclosure
  const matched = hypotheses.filter(h => h.status === 'matched')
  const remaining = hypotheses.filter(h => h.status !== 'matched')

  // Controls whether the non-matched hypotheses are visible
  const [showRemaining, setShowRemaining] = useState(false)

  return (
    <div
      className="p-4 rounded-lg border"
      style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', fontFamily: "'Fira Sans', sans-serif" }}
    >
      {/* Section header — renamed from "Hypothesis Evaluation" to "Root Cause Analysis" */}
      <div
        className="text-xs font-semibold uppercase tracking-wider mb-3"
        style={{ color: 'var(--text-muted)' }}
      >
        Root Cause Analysis
      </div>

      <div className="flex flex-col gap-1.5">
        {/* Matched hypotheses — always visible, highlighted as findings */}
        {matched.map((h) => (
          <div
            key={h.category}
            className="flex items-center gap-3 px-3 py-2 rounded"
            style={{ background: 'var(--accent-light)' }}
          >
            <span
              className="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold"
              style={{ background: 'var(--accent)', color: 'white', fontSize: '10px' }}
            >
              ★
            </span>
            <span
              className="flex-1 text-sm"
              style={{ color: 'var(--text-primary)', fontWeight: 600 }}
            >
              {CATEGORY_LABELS[h.category] || h.category}
            </span>
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{ background: 'var(--accent-light)', color: 'var(--accent)', fontWeight: 500 }}
            >
              matched
            </span>
          </div>
        ))}

        {/* Expand/collapse toggle for remaining hypotheses */}
        {remaining.length > 0 && (
          <button
            onClick={() => setShowRemaining(!showRemaining)}
            className="flex items-center gap-2 px-3 py-2 rounded text-xs text-left"
            style={{ color: 'var(--text-muted)', background: 'transparent', border: 'none', cursor: 'pointer' }}
          >
            {/* Chevron rotates when expanded */}
            <span
              className="transition-transform duration-200"
              style={{
                display: 'inline-block',
                transform: showRemaining ? 'rotate(90deg)' : 'rotate(0deg)',
              }}
            >
              ▶
            </span>
            <span>
              {remaining.length} other hypothesis{remaining.length !== 1 ? 'es' : ''} not consistent with observed pattern
            </span>
          </button>
        )}

        {/* Remaining hypotheses — only visible when expanded */}
        {showRemaining && remaining.map((h) => (
          <div
            key={h.category}
            className="flex items-center gap-3 px-3 py-2 rounded"
            style={{ background: 'transparent' }}
          >
            <span
              className="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold"
              style={{ background: 'var(--bg-input)', color: 'var(--text-muted)', fontSize: '10px' }}
            >
              ○
            </span>
            <span
              className="flex-1 text-sm"
              style={{ color: 'var(--text-muted)', fontWeight: 400 }}
            >
              {CATEGORY_LABELS[h.category] || h.category}
            </span>
            {/* "not indicated" is more informative than "not evaluated" — it tells the reader
                the pattern didn't point to this hypothesis, not just that we skipped it */}
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{ background: 'var(--bg-input)', color: 'var(--text-muted)', fontWeight: 500 }}
            >
              not indicated
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
