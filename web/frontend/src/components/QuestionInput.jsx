// QuestionInput.jsx — scenario switcher pills + input bar.
//
// WHY pills instead of a dropdown: pills show all available scenarios at a glance
// and are one-click to switch. A dropdown would require two clicks and hides options.
// This pattern works well when there are 2-4 options (our current count).
//
// WHY derived from SCENARIOS: the pill list was previously hardcoded, which meant
// adding a new scenario required updating two files. Now pills are derived from the
// SCENARIOS object, so adding a scenario to scenarios.js automatically shows it here.
//
// WHY the input is disabled: the input bar is a UX affordance showing WHERE users
// will type future questions when the live backend is connected. In Phase 1 mock mode,
// it's read-only with a placeholder so the UI looks complete without being misleading.

import { SCENARIOS, SCENARIO_KEYS } from '../data/scenarios'

// Derive pill labels from scenario data.
// Uses the verdict_label from the diagnosis as the pill display name.
// Falls back to a formatted version of the scenario key if verdict_label is missing.
const SCENARIO_PILLS = SCENARIO_KEYS.map(key => ({
  key,
  label: SCENARIOS[key]?.diagnosis?.verdict_label || key.replace(/_/g, ' '),
}))

export default function QuestionInput({ placeholder, activeScenario, onScenarioChange }) {
  return (
    <div
      className="px-6 py-4 border-t"
      style={{
        background: 'var(--bg-card)',
        borderColor: 'var(--border)',
        fontFamily: "'Fira Sans', sans-serif",
      }}
    >
      {/* Scenario pills — centered so they read as navigation, not form controls */}
      <div className="flex gap-2 mb-3 justify-center">
        {SCENARIO_PILLS.map((pill) => (
          <button
            key={pill.key}
            onClick={() => onScenarioChange(pill.key)}
            className="px-3 py-1.5 rounded-full text-xs font-medium transition-colors"
            style={{
              // Active pill uses accent fill; inactive uses muted background
              background: activeScenario === pill.key ? 'var(--accent)' : 'var(--bg-input)',
              color: activeScenario === pill.key ? 'white' : 'var(--text-secondary)',
              border: `1px solid ${activeScenario === pill.key ? 'var(--accent)' : 'var(--border)'}`,
            }}
          >
            {pill.label}
          </button>
        ))}
      </div>

      {/* Input row — disabled in mock mode, will be enabled when backend is live */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder={placeholder}
          className="flex-1 px-4 py-2.5 rounded-lg text-sm"
          style={{
            background: 'var(--bg-input)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
            outline: 'none',
          }}
          readOnly
        />
        <button
          className="px-4 py-2.5 rounded-lg text-sm font-medium"
          style={{
            background: 'var(--accent)',
            color: 'white',
            border: 'none',
            cursor: 'not-allowed',
            opacity: 0.6,
          }}
          disabled
        >
          Investigate
        </button>
      </div>
    </div>
  )
}
