# Requirements Notes

This file is for human review and brainstorming. It is intentionally separate from `ROADMAP.md` because the SolidWorks-style Feature Manager target needs design decisions, Fusion API feasibility checks, and user workflow review before implementation.

## Product Goal

Build a left-side Fusion feature/history manager inspired by SolidWorks FeatureManager: readable, dense, keyboard-friendly, and useful for complex parametric models with hundreds of features.

The target is not a cosmetic clone. The target is equivalent workflow value where Fusion's API allows it.

## Open Requirement Areas

### Core Object Model

- What should the top-level tree represent: full document timeline, active component history, component hierarchy, or selectable modes?
- How should timeline groups map to tree groups?
- Should naming conventions like `00_REFERENCE_LAYOUT` become visual folders, filters, or just ordinary timeline entries?
- How should components, bodies, sketches, construction geometry, and features be visually distinguished?

### Selection and Navigation

- Single-click behavior.
- Double-click behavior.
- F2 rename behavior.
- Arrow-key navigation.
- Enter behavior.
- Escape behavior.
- Multi-select feasibility.
- Synchronization between Fusion selection and palette selection.

### Editing and Commands

- Rename timeline entry.
- Edit feature.
- Roll to feature.
- Roll before/after feature.
- Suppress/unsuppress if exposed.
- Open sketch if exposed.
- Component visibility/isolation if useful.
- Context menu command set.

### Status and Diagnostics

- Broken or warning features.
- Suppressed features.
- Rolled-back features.
- Features after timeline marker.
- API-inaccessible features.
- Non-parametric design state.

### Large Model UX

- Search.
- Filter by component.
- Filter by feature type.
- Collapse/expand groups.
- Persist collapsed state.
- Virtualized rendering if full rebuilds are too slow.
- Debounced refresh.

### Visual Design

- SolidWorks-like dense left tree.
- Clear icons and names.
- Minimal chrome.
- High contrast selection state.
- Compact rows.
- Usable hover/focus states.
- Avoid decorative redesign until workflow is correct.

### Fusion API Feasibility Questions

- Can current Fusion reliably expose timeline item health/status?
- Can current Fusion expose stable ids for timeline entries across refreshes?
- Can timeline marker position be changed precisely enough for rollback/insert workflows?
- Can palette interactions trigger all relevant edit commands safely?
- Can native Fusion selection changes be observed and mirrored into the palette?
- Can groups be created, renamed, expanded, collapsed, or queried reliably?
- Can feature reorder or dependency tree behavior be exposed at all?

## Decision Log

- Start from the existing VerticalTimeline add-in rather than rewriting immediately.
- Fix known upstream bugs and runtime crashes first.
- Use Fusion MCP for runtime inspection and test loops.
- Treat SolidWorks-style behavior as an aspirational target constrained by Fusion API capability.

