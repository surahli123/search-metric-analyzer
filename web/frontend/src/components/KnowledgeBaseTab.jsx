// KnowledgeBaseTab.jsx — Read-only browser for the system's domain knowledge files.
//
// WHY this tab exists: The diagnostic system draws on 6 YAML knowledge files to
// analyze metric movements. Showing users what knowledge the system has builds trust
// and transparency — they can verify the system's reasoning is grounded in real
// domain knowledge, not hallucinated. This is especially important for a diagnostic
// tool where users need to trust the output.
//
// LAYOUT: Centered container (max-width 960px, matching InvestigateTab) with a
// page header and a vertical stack of KnowledgeCard components. Each card is
// expandable to show the file's internal sections.
//
// DATA: Reads from knowledge_index.js (static metadata), NOT from the actual YAML
// files. This keeps the tab fully client-side with no backend dependency — same
// pattern as scenarios.js powering the InvestigateTab.
//
// No props needed — Knowledge Base content is scenario-independent.

import { KNOWLEDGE_FILES } from '../data/knowledge_index'
import KnowledgeCard from './KnowledgeCard'

export default function KnowledgeBaseTab() {
  return (
    <div className="mx-auto w-full px-6 py-6" style={{ maxWidth: 960 }}>
      {/* Page header — title + subtitle explaining what this tab shows */}
      <div className="mb-6">
        <h2
          className="text-lg font-semibold mb-1"
          style={{
            color: 'var(--text-primary)',
            fontFamily: "'Fira Sans', sans-serif",
          }}
        >
          Domain Knowledge
        </h2>
        <p
          className="text-sm"
          style={{
            color: 'var(--text-secondary)',
            fontFamily: "'Fira Sans', sans-serif",
            lineHeight: '1.5',
          }}
        >
          The diagnostic system draws on these knowledge files to analyze metric movements.
        </p>
      </div>

      {/* Knowledge file cards — one per YAML file, vertically stacked with gap-4
          spacing to match the component stack pattern in InvestigateTab */}
      <div className="flex flex-col gap-4">
        {KNOWLEDGE_FILES.map((file) => (
          <KnowledgeCard key={file.id} file={file} />
        ))}
      </div>

      {/* File count footer — helps users verify they're seeing the full set */}
      <div
        className="mt-6 text-xs text-center"
        style={{
          color: 'var(--text-muted)',
          fontFamily: "'Fira Code', monospace",
        }}
      >
        {KNOWLEDGE_FILES.length} knowledge files
      </div>
    </div>
  )
}
