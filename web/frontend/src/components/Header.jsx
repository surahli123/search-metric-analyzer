/**
 * Header.jsx — top-of-page header with product name, tagline, and 3-tab navigation.
 *
 * LAYOUT: two-zone flex row
 *   Left  — product name + tagline (stacked vertically)
 *   Right — 3 tab buttons: Investigate | Trace | Knowledge Base
 *
 * TAB STYLING:
 *   Active tab  → accent-light background + accent text color (blue pill)
 *   Inactive tab → text-muted color, transparent background (subtle, clickable)
 *
 * WHY props instead of internal state: The active tab is owned by App.jsx because
 * it determines which tab CONTENT to render. Header just reflects that state
 * and forwards click events up. This is React's "lift state up" pattern.
 *
 * Props:
 *   activeTab   {string}   — Current tab key: 'investigate' | 'trace' | 'knowledge'
 *   onTabChange {function} — Called with tab key when user clicks a tab button
 */

// Tab configuration — defines the mapping between internal keys and display labels.
// Centralized here so adding a new tab is a one-line change, not a hunt through JSX.
const TABS = [
  { key: 'investigate', label: 'Investigate' },
  { key: 'trace', label: 'Trace' },
  { key: 'knowledge', label: 'Knowledge Base' },
]

export default function Header({ activeTab, onTabChange }) {
  return (
    <header
      className="flex items-center justify-between px-6 py-3 border-b"
      style={{
        background: 'var(--bg-card)',
        borderColor: 'var(--border)',
        fontFamily: "'Fira Sans', sans-serif",
      }}
    >
      {/* Left zone: product name + tagline stacked vertically */}
      <div className="flex flex-col">
        <span
          className="text-lg font-semibold"
          style={{ color: 'var(--text-primary)' }}
        >
          Search Metric Analyzer
        </span>
        {/* Tagline — explains what the tool does in one line.
            Uses text-muted so it's visible but doesn't compete with the product name. */}
        <span
          className="text-xs"
          style={{ color: 'var(--text-muted)' }}
        >
          AI-powered root cause analysis for search metric movements
        </span>
      </div>

      {/* Right zone: tab navigation buttons */}
      <nav className="flex gap-1">
        {TABS.map(({ key, label }) => {
          const isActive = activeTab === key
          return (
            <button
              key={key}
              onClick={() => onTabChange(key)}
              className={`px-3 py-1.5 rounded text-sm ${isActive ? 'font-medium' : ''}`}
              style={{
                // Active: accent-light bg + accent text (blue pill effect)
                // Inactive: no bg + muted text (clickable but understated)
                background: isActive ? 'var(--accent-light)' : 'transparent',
                color: isActive ? 'var(--accent)' : 'var(--text-muted)',
              }}
            >
              {label}
            </button>
          )
        })}
      </nav>
    </header>
  )
}
