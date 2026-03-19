// TraceTab.jsx — top-level container for the pipeline execution trace viewer.
//
// WHY this tab exists: The diagnostic pipeline has 4 stages (UNDERSTAND, HYPOTHESIZE,
// DISPATCH, SYNTHESIZE) that each perform multiple operations — SQL queries, knowledge
// lookups, reasoning steps. Engineers debugging a wrong diagnosis need to see exactly
// what happened at each stage, not just the final output. This is the "show your work"
// principle applied to AI-assisted diagnostics.
//
// WHY filter pills: With 15+ steps across 4 phases, engineers often want to focus on
// one type. "Show me just the SQL" or "show me just the reasoning" are common debugging
// patterns. The filter works by passing a type string down to TracePhaseCard, which
// hides non-matching steps while keeping phase headers visible for pipeline context.
//
// ARCHITECTURE: This component owns the filter state (activeFilter via useState) and
// reads trace data directly from TRACE_DATA. Each phase is rendered by TracePhaseCard,
// which owns its own expand/collapse state. This keeps state close to where it's used.
//
// Props:
//   scenarioKey {string} — Which scenario's trace to display (e.g., 'within_variance')

import { useState } from 'react'
import { TRACE_DATA } from '../data/scenarios'
import TracePhaseCard from './TracePhaseCard'

// Filter options — 'all' plus one for each step type that appears in trace data.
// The value is the type string that gets passed to TracePhaseCard's filter prop.
// Using an array of objects (not just strings) so we can have display labels
// that differ from the filter values (e.g., "All" vs "all").
const FILTERS = [
  { label: 'All',       value: 'all' },
  { label: 'SQL',       value: 'sql' },
  { label: 'Knowledge', value: 'knowledge' },
  { label: 'Reasoning', value: 'reasoning' },
  { label: 'Output',    value: 'output' },
]

export default function TraceTab({ scenarioKey }) {
  // Active filter — controls which step types are visible across all phases.
  // Default 'all' shows everything, matching the "overview first" design principle.
  const [activeFilter, setActiveFilter] = useState('all')

  // Look up trace data for the active scenario.
  // If not found (e.g., new scenario without trace data yet), show empty state.
  const traceData = TRACE_DATA[scenarioKey]

  if (!traceData) {
    return (
      <div
        className="flex items-center justify-center py-16"
        style={{ color: 'var(--text-muted)', fontFamily: "'Fira Sans', sans-serif" }}
      >
        No trace data available
      </div>
    )
  }

  return (
    <div className="mx-auto w-full" style={{ maxWidth: 960 }}>
      {/* Filter pills — horizontal row of type filters at top of trace view */}
      <div className="px-6 pt-6 pb-4 flex gap-2">
        {FILTERS.map(f => {
          const isActive = activeFilter === f.value
          return (
            <button
              key={f.value}
              onClick={() => setActiveFilter(f.value)}
              className="px-3 py-1.5 rounded-full text-xs font-medium transition-colors"
              style={{
                // Active pill gets accent background + white text (high contrast).
                // Inactive pills get subtle background + muted text (low contrast).
                // This follows the same active/inactive pattern as the header tabs.
                background: isActive ? 'var(--accent)' : 'var(--bg-input)',
                color: isActive ? 'white' : 'var(--text-secondary)',
                fontFamily: "'Fira Sans', sans-serif",
                cursor: 'pointer',
                border: 'none',
              }}
            >
              {f.label}
            </button>
          )
        })}
      </div>

      {/* Phase cards — one card per pipeline stage, stacked vertically */}
      <div className="px-6 pb-6 flex flex-col gap-3">
        {traceData.phases.map(phase => (
          <TracePhaseCard
            key={phase.name}
            phase={phase}
            filter={activeFilter}
          />
        ))}
      </div>
    </div>
  )
}
