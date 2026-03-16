/**
 * HypothesisChecklist — ordered hypothesis evaluation list.
 * DS Lead Fix 2: Only "matched" and "not_evaluated" statuses.
 * Props: hypotheses (array of {category, status, reason?})
 */
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
  return (
    <div className="p-4 rounded-lg border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', fontFamily: "'Fira Sans', sans-serif" }}>
      <div className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: 'var(--text-muted)' }}>Hypothesis Evaluation (priority order)</div>
      <div className="flex flex-col gap-1.5">
        {hypotheses.map((h) => {
          const isMatched = h.status === 'matched'
          return (
            <div key={h.category} className="flex items-center gap-3 px-3 py-2 rounded" style={{ background: isMatched ? 'var(--accent-light)' : 'transparent' }}>
              <span className="inline-flex items-center justify-center w-5 h-5 rounded-full text-xs font-bold" style={{ background: isMatched ? 'var(--accent)' : 'var(--bg-input)', color: isMatched ? 'white' : 'var(--text-muted)', fontSize: '10px' }}>
                {isMatched ? '★' : '○'}
              </span>
              <span className="flex-1 text-sm" style={{ color: isMatched ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: isMatched ? 600 : 400 }}>
                {CATEGORY_LABELS[h.category] || h.category}
              </span>
              <span className="text-xs px-2 py-0.5 rounded" style={{ background: isMatched ? 'var(--accent-light)' : 'var(--bg-input)', color: isMatched ? 'var(--accent)' : 'var(--text-muted)', fontWeight: 500 }}>
                {isMatched ? 'matched' : 'not evaluated'}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
