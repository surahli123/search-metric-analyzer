/**
 * Header.jsx
 *
 * Static top-of-page header for the Search Metric Analyzer web app.
 *
 * Layout: two-zone flex row
 *   Left  — product name + BETA badge
 *   Right — nav tabs (Dashboard disabled, Agent active)
 *
 * No props — this component is fully static.
 * Styling uses CSS custom properties defined in the app's global stylesheet
 * so the design tokens stay in one place and this component picks them up automatically.
 */
export default function Header() {
  return (
    <header className="flex items-center justify-between px-6 py-3 border-b" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)', fontFamily: "'Fira Sans', sans-serif" }}>
      <div className="flex items-center gap-2">
        <span className="text-lg font-semibold" style={{ color: 'var(--text-primary)' }}>Search Metric Analyzer</span>
        <span className="text-xs px-2 py-0.5 rounded" style={{ background: 'var(--accent-light)', color: 'var(--accent)', fontWeight: 600 }}>BETA</span>
      </div>
      <nav className="flex gap-1">
        {/* Dashboard tab is disabled — not yet implemented */}
        <button className="px-3 py-1.5 rounded text-sm" style={{ color: 'var(--text-muted)', cursor: 'not-allowed' }} disabled>Dashboard</button>
        {/* Agent tab is the active view */}
        <button className="px-3 py-1.5 rounded text-sm font-medium" style={{ background: 'var(--accent-light)', color: 'var(--accent)' }}>Agent</button>
      </nav>
    </header>
  )
}
