// CollapsibleSection.jsx — reusable expand/collapse wrapper with chevron + title.
//
// WHY: Progressive disclosure. Instead of showing 14 components in one scroll,
// we group them into collapsible tiers (Answer > Evidence > Technical).
// This is the "build in stages you can see" principle applied to UI.
//
// Props:
//   title     {string}  — Section header text, e.g. "Supporting Evidence"
//   count     {number}  — Optional item count badge, e.g. 5
//   defaultOpen {boolean} — Whether section starts expanded (default: true)
//   children  {node}    — The content to show/hide

import { useState } from 'react'

export default function CollapsibleSection({ title, count, defaultOpen = true, children }) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  return (
    <div>
      {/* Clickable header row — toggles expand/collapse */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 w-full py-2 text-left"
        style={{ fontFamily: "'Fira Sans', sans-serif" }}
        aria-expanded={isOpen}
      >
        {/* Chevron rotates on expand */}
        <span
          className="text-xs transition-transform duration-200"
          style={{
            color: 'var(--text-muted)',
            transform: isOpen ? 'rotate(90deg)' : 'rotate(0deg)',
            display: 'inline-block',
          }}
        >
          ▶
        </span>

        {/* Section title */}
        <span
          className="text-xs font-semibold uppercase tracking-wider"
          style={{ color: 'var(--text-muted)' }}
        >
          {title}
        </span>

        {/* Optional item count badge */}
        {count !== undefined && (
          <span
            className="text-xs px-1.5 py-0.5 rounded"
            style={{ background: 'var(--bg-input)', color: 'var(--text-muted)' }}
          >
            {count}
          </span>
        )}
      </button>

      {/* Collapsible content area */}
      {isOpen && (
        <div className="flex flex-col gap-4">
          {children}
        </div>
      )}
    </div>
  )
}
