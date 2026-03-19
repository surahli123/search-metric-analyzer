// App.jsx — root assembly that manages tab navigation and scenario state.
//
// ARCHITECTURE: This is the single stateful component in the app. It owns two
// pieces of state:
//   1. activeTab   — which tab is shown ('investigate' | 'trace' | 'knowledge')
//   2. scenarioKey — which mock scenario is active (drives InvestigateTab content)
//
// Tab content is conditionally rendered based on activeTab. Each tab component
// is a self-contained view that receives only the data it needs via props.
//
// WHY state lives here: Both the Header (which tab button is highlighted) and
// the tab content (which component renders) depend on activeTab. Lifting state
// to the nearest common ancestor (App) is React's standard pattern for this.
//
// SCENARIO SWITCHING: scenarioKey lives at App level because it may be shared
// across tabs (e.g., Trace tab shows trace data for the same scenario). When
// the user clicks a scenario pill in InvestigateTab, the callback propagates
// up to App, which updates scenarioKey and re-renders the active tab.

import { useState } from 'react'
import { SCENARIOS, DEFAULT_SCENARIO } from './data/scenarios'

// App chrome — the header is always visible regardless of active tab
import Header from './components/Header'

// Tab content components — only one renders at a time based on activeTab
import InvestigateTab from './components/InvestigateTab'
import TraceTab from './components/TraceTab'
import KnowledgeBaseTab from './components/KnowledgeBaseTab'

function App() {
  // activeTab controls which tab content is rendered.
  // Default to 'investigate' since that's the primary workflow.
  const [activeTab, setActiveTab] = useState('investigate')

  // scenarioKey drives which scenario data is displayed.
  // Shared at App level so multiple tabs can reference the same scenario.
  const [scenarioKey, setScenarioKey] = useState(DEFAULT_SCENARIO)

  // Look up the full scenario object from the key
  const scenario = SCENARIOS[scenarioKey]

  return (
    // Outer wrapper: full-height flex column
    // The Header is fixed at top, tab content fills remaining space
    <div className="min-h-screen flex flex-col" style={{ background: 'var(--bg-page)' }}>

      {/* Header — always visible, owns the tab navigation UI */}
      <Header activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Tab content area — conditionally renders based on activeTab.
          Each tab manages its own internal layout (scrolling, padding, etc).
          App just provides the data each tab needs via props. */}
      {activeTab === 'investigate' && (
        <InvestigateTab
          scenario={scenario}
          scenarioKey={scenarioKey}
          onScenarioChange={setScenarioKey}
        />
      )}

      {activeTab === 'trace' && (
        <TraceTab scenarioKey={scenarioKey} />
      )}

      {activeTab === 'knowledge' && (
        <KnowledgeBaseTab />
      )}
    </div>
  )
}

export default App
