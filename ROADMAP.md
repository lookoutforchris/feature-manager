# Roadmap

This project started from an abandoned Fusion timeline add-in and should evolve cautiously. The first goal is not a rewrite. The first goal is a stable, observable add-in that can be tested against current Fusion behavior.

## Phase 0: Upstream Stabilization

Purpose: make the existing Feature Manager baseline reliable enough to use as a foundation.

- Keep the defensive `ui.activeWorkspace` handling for Fusion document/workspace transitions.
- Verify the installed add-in loads cleanly in current Fusion.
- Confirm the `featuremanagerlib` submodule is packaged or documented so install failures are avoidable.
- Replace or reduce intrusive error dialogs where practical.
- Capture diagnostic output for startup, palette creation, document activation, workspace activation, timeline refresh, and HTML events.
- Record runtime failures in `CURRENT_STATUS.md`.

## Phase 1: Upstream TODO and Bug Debt

Purpose: resolve known debt before adding major new behavior.

- Improve performance on larger timelines.
- Fix nested coloring not reused in new documents.
- Highlight the feature selected in the Fusion GUI when possible.
- Correctly select and edit primitive features such as `BoxFeature`, `CylinderFeature`, and similar feature objects inside components.
- Re-check whether current Fusion still blocks `Move` feature entity access.
- Re-check whether current Fusion still requires the document/workspace activation workaround.
- Improve occurrence type detection in `featuremanagerlib.timeline.get_occurrence_type()`.

## Phase 2: Measurement and Test Harness

Purpose: make development faster and less subjective.

- Use Fusion MCP as the preferred runtime inspection and test loop.
- Build small scripted test models with known timeline contents.
- Create baseline tests for simple, nested component, grouped, rolled-back, suppressed, and non-parametric designs.
- Measure refresh time for representative timelines, including 100, 400, and 800 feature cases.
- Document Fusion API limitations found during testing.

## Phase 3: Feature Manager Foundation

Purpose: turn the palette into a practical manager without overcommitting to impossible API behavior.

- Preserve oldest-to-newest vertical history order.
- Show feature icon, visible feature name, status, and component context.
- Add robust selection state in the palette.
- Add keyboard navigation.
- Add search/filter.
- Improve rename UX.
- Replace ad hoc right-click behavior with a deliberate context menu.
- Add clear handling for groups/folders and collapsed state.
- Add component/local-history filtering if Fusion exposes enough context.

## Phase 4: SolidWorks-Style Requirements Track

Purpose: define the target experience before implementing a full redesign.

This phase requires human review and brainstorming. The goal is "as close to SolidWorks FeatureManager as Fusion allows," but the exact requirements are not settled yet.

Requirements should be split into:

- Missing capabilities: behaviors Fusion lacks or exposes differently.
- UX/UI requirements: layout, visual density, selection behavior, keyboard model, context menus, and terminology.
- API feasibility: what Fusion exposes directly, what needs workarounds, and what cannot be done safely.
- Packaging requirements: install, update, icons, documentation, versioning, and possible Autodesk Add-in Store readiness.

## Near-Term Priority

1. Finish manual verification of the current patched add-in.
2. Update `CURRENT_STATUS.md` with observed working and broken behavior.
3. Triage Phase 1 bugs into small patches.
4. Start a requirements review document for the SolidWorks-style manager.
