// TracePhaseCard.jsx — expandable card for one phase of the diagnostic pipeline.
//
// WHY expandable: The trace can have 15+ steps across 4 phases. Collapsing completed
// phases lets engineers focus on the phase they're debugging while keeping the full
// pipeline visible for context. This is progressive disclosure applied to execution traces.
//
// WHY status dots: A colored dot (green/amber/gray) gives instant pipeline status
// at a glance — like a CI build dashboard. Green = done, amber = running, gray = waiting.
// In Phase 2 (SSE streaming), the "active" dot will pulse to show live execution.
//
// Props:
//   phase  {object} — One phase from TRACE_DATA:
//     - name      {string}  — 'UNDERSTAND' | 'HYPOTHESIZE' | 'DISPATCH' | 'SYNTHESIZE'
//     - status    {string}  — 'done' | 'active' | 'pending'
//     - duration_s {number} — Total phase execution time
//     - steps     {array}   — Array of step objects (passed to TraceStep)
//   filter {string} — Active filter type: 'all' | 'sql' | 'knowledge' | 'reasoning' | 'output'

import { useState } from 'react'
import TraceStep from './TraceStep'

// Maps status to the CSS variable for the dot color.
// Uses semantic tokens from the design system rather than hardcoded colors.
const STATUS_DOT_COLORS = {
  done:    'var(--green)',
  active:  'var(--amber)',
  pending: 'var(--text-muted)',
}

export default function TracePhaseCard({ phase, filter }) {
  // Default expanded — engineers usually want to see all steps on first load.
  // They collapse phases as they verify them, like checking off pipeline stages.
  const [isExpanded, setIsExpanded] = useState(true)

  const { name, status, duration_s, steps } = phase

  // Apply the type filter: 'all' shows everything, otherwise only matching types.
  // This filtering happens at the card level so phase headers always remain visible
  // (even if all their steps are filtered out), maintaining pipeline structure.
  const visibleSteps = filter === 'all'
    ? steps
    : steps.filter(s => s.type === filter)

  const dotColor = STATUS_DOT_COLORS[status] || STATUS_DOT_COLORS.pending

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}
    >
      {/* Clickable header — phase name + status dot + step count + timing */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-3 w-full px-4 py-3 text-left"
        style={{ fontFamily: "'Fira Sans', sans-serif" }}
        aria-expanded={isExpanded}
      >
        {/* Status dot — semantic color indicates pipeline progress */}
        <span
          data-testid="status-dot"
          className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
          style={{
            background: dotColor,
            // Pulse animation for active phases — draws attention to running step
            animation: status === 'active' ? 'pulse 2s ease-in-out infinite' : 'none',
          }}
        />

        {/* Phase name — uppercase for pipeline stage emphasis */}
        <span
          className="text-sm font-semibold"
          style={{ color: 'var(--text-primary)' }}
        >
          {name}
        </span>

        {/* Step count — helps engineers know how many operations a phase performed */}
        <span
          className="text-xs px-1.5 py-0.5 rounded"
          style={{ background: 'var(--bg-input)', color: 'var(--text-muted)' }}
        >
          {steps.length} steps
        </span>

        {/* Timing — how long this phase took (important for performance debugging) */}
        <span
          className="text-xs ml-auto"
          style={{
            color: 'var(--text-muted)',
            fontFamily: "'Fira Code', monospace",
          }}
        >
          {duration_s}s
        </span>

        {/* Chevron — rotates on expand, matching CollapsibleSection pattern */}
        <span
          className="text-xs transition-transform duration-200"
          style={{
            color: 'var(--text-muted)',
            transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
            display: 'inline-block',
          }}
        >
          ▶
        </span>
      </button>

      {/* Step list — only shown when expanded */}
      {isExpanded && visibleSteps.length > 0 && (
        <div className="px-3 pb-3 flex flex-col gap-1.5">
          {visibleSteps.map((step, i) => (
            <TraceStep key={`${step.type}-${step.label}-${i}`} step={step} />
          ))}
        </div>
      )}
    </div>
  )
}
