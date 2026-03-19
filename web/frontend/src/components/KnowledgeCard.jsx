// KnowledgeCard.jsx — Expandable card showing one knowledge file's metadata.
//
// WHY expandable: There are 6 knowledge files with 2-4 sections each. Showing all
// sections at once would create a wall of text. The expand/collapse pattern (same as
// MethodologyBlock.jsx) lets users scan file names and descriptions quickly, then
// drill into sections for the files they care about.
//
// PATTERN: Follows the same card style as NarrativeBlock (rounded-lg border, bg-card)
// and the same expand/collapse pattern as MethodologyBlock (useState, chevron rotation).
//
// Props:
//   file {object} — One entry from KNOWLEDGE_FILES (knowledge_index.js)
//     .id          {string}   — Unique identifier for the knowledge file
//     .name        {string}   — Human-readable file name, e.g. "Metric Definitions"
//     .file        {string}   — Relative path to the YAML file
//     .description {string}   — One-sentence description of the file's contents
//     .sections    {array}    — Array of { key, label, summary } for each YAML section

import { useState } from 'react'

export default function KnowledgeCard({ file }) {
  // Track whether the section list is visible — collapsed by default
  // to keep the page scannable when all 6 cards are rendered
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
      {/* Clickable header — shows file name, description, and expand chevron.
          Full-width button so the entire row is a click target. */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-start gap-3 px-4 py-3 text-left"
        style={{ fontFamily: "'Fira Sans', sans-serif" }}
        aria-expanded={isOpen}
      >
        {/* Colored dot — visual anchor for scanning the card list.
            Uses accent color to tie into the app's brand blue. */}
        <span
          className="inline-block w-2 h-2 rounded-full flex-shrink-0 mt-1.5"
          style={{ background: 'var(--accent)' }}
        />

        {/* Name + description column — takes remaining width */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className="text-sm font-semibold"
              style={{ color: 'var(--text-primary)' }}
            >
              {file.name}
            </span>

            {/* Section count badge — tells user how much detail is inside */}
            <span
              className="text-xs px-1.5 py-0.5 rounded"
              style={{
                background: 'var(--bg-input)',
                color: 'var(--text-muted)',
              }}
            >
              {file.sections.length} {file.sections.length === 1 ? 'section' : 'sections'}
            </span>
          </div>

          {/* File description — secondary text for context without expanding */}
          <div
            className="text-xs mt-1"
            style={{ color: 'var(--text-secondary)', lineHeight: '1.5' }}
          >
            {file.description}
          </div>
        </div>

        {/* Chevron indicator — rotates when expanded (same pattern as MethodologyBlock) */}
        <span
          className="text-xs flex-shrink-0 mt-1"
          style={{
            color: 'var(--text-muted)',
            transform: isOpen ? 'rotate(180deg)' : 'none',
            display: 'inline-block',
            transition: 'transform 200ms ease',
          }}
        >
          &#9660;
        </span>
      </button>

      {/* Expanded section list — only rendered when open (not just hidden with CSS)
          to keep the DOM clean when most cards are collapsed. */}
      {isOpen && (
        <div className="px-4 pb-4">
          {/* Divider between header and sections */}
          <div
            className="mb-3"
            style={{ borderTop: '1px solid var(--border)' }}
          />

          {/* Section rows — each shows a YAML section key, human label, and summary */}
          <div className="flex flex-col gap-3">
            {file.sections.map((section) => (
              <div
                key={section.key}
                className="flex items-start gap-3 px-3 py-2 rounded"
                style={{ background: 'var(--bg-elevated)' }}
              >
                {/* Section label — styled as a small tag/badge for scannability */}
                <span
                  className="text-xs font-medium px-2 py-0.5 rounded flex-shrink-0"
                  style={{
                    background: 'var(--accent-light)',
                    color: 'var(--accent)',
                    fontFamily: "'Fira Sans', sans-serif",
                  }}
                >
                  {section.label}
                </span>

                {/* Section summary — the one-line description of what's in this section */}
                <span
                  className="text-xs"
                  style={{
                    color: 'var(--text-secondary)',
                    fontFamily: "'Fira Sans', sans-serif",
                    lineHeight: '1.5',
                  }}
                >
                  {section.summary}
                </span>
              </div>
            ))}
          </div>

          {/* File path footer — monospace to signal "this is a real file path".
              Helps power users find the actual YAML file on disk. */}
          <div
            className="mt-3 text-xs px-1"
            style={{
              color: 'var(--text-muted)',
              fontFamily: "'Fira Code', monospace",
            }}
          >
            {file.file}
          </div>
        </div>
      )}
    </div>
  )
}
