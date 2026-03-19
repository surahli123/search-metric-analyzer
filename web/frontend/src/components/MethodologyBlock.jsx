// MethodologyBlock.jsx — collapsible section showing how the analysis was run.
//
// WHY collapsed by default: methodology is "trust but verify" content. Most users
// don't need it; power users and engineers want to inspect it. Hiding it by default
// keeps the main reading flow clean while keeping full transparency one click away.
//
// The data_context shape comes from scenarios.js and will later come from the
// FastAPI backend's /investigate endpoint.

import { useState } from 'react'

export default function MethodologyBlock({ dataContext }) {
  // isOpen controls whether the detail rows are visible
  const [isOpen, setIsOpen] = useState(false)

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{
        background: 'var(--bg-card)',
        borderColor: 'var(--border)',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      {/* Toggle button — full width so the whole header row is clickable */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
        style={{ fontFamily: "'Fira Sans', sans-serif" }}
      >
        <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          Methodology & Data Sources
        </span>
        {/* Chevron rotates 180° when open — CSS transform is cheaper than swapping icons */}
        <span
          className="text-xs"
          style={{
            color: 'var(--text-muted)',
            transform: isOpen ? 'rotate(180deg)' : 'none',
            display: 'inline-block',
          }}
        >
          ▼
        </span>
      </button>

      {/* Detail rows — only rendered when open (not just hidden) to keep DOM clean */}
      {isOpen && (
        <div
          className="px-4 pb-4 text-xs grid gap-2"
          style={{
            color: 'var(--text-secondary)',
            fontFamily: "'Fira Code', monospace",
          }}
        >
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Data source: </span>
            {dataContext.data_source}
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Queries analyzed: </span>
            {dataContext.queries_analyzed}
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Metric formula: </span>
            {dataContext.metric_formula}
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Filters: </span>
            {dataContext.filters_applied?.join(' AND ')}
          </div>
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Data freshness: </span>
            {dataContext.data_freshness?.status} ({dataContext.data_freshness?.status_note})
          </div>
        </div>
      )}
    </div>
  )
}
