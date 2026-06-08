# Current Status

## Milestone 1 Snapshot

This repository is a direct clone of `original-author/VerticalTimeline` with the `featuremanagerlib` submodule present. The initial stabilization change is intentionally small and keeps the existing UI and event model intact.

Pre-group-management restore point: git commit `eeb5eee` (`Milestone: Feature Manager core interactions`).

Current release-candidate checkpoint: git commit `7f6c989` (`Release candidate: transparent Feature Manager design`). This checkpoint includes the transparent palette experiment, Browser-style floating visual treatment, built-in group management, drag-to-reorder, draggable history marker, and expanded context-menu command plumbing.

## What Was Fixed

`ui.activeWorkspace` is no longer read directly from document activation, workspace activation, or the toggle command. A new defensive helper treats Fusion transition-time `RuntimeError` failures as "no valid active workspace yet" and logs the condition instead of letting the add-in crash.

The specific reported crash was:

```text
RuntimeError: 2 : InternalValidationError : pActiveEnvironment
```

This is now handled when Fusion temporarily cannot provide `ui.activeWorkspace`.

## What Works From Static Inspection

The add-in entry points are `run(context)` and `stop(context)` in `VerticalTimeline.py`.

Palette creation uses `ui.palettes.addTransparent()` with `palette.html`, docks left, and communicates through Fusion HTML palette events.

Timeline refresh flows through `invalidate()`, which calls `featuremanagerlib.timeline.get_timeline()`, builds feature data, and sends `setTimeline` to the palette.

Existing HTML event actions include readiness, feature rename, feature select, feature edit, and roll-to behavior.

## Verified In Fusion

Fusion MCP first-class tools are available from Codex in VS Code.

Runtime checks completed:

- `fusion_mcp_read` listed the active Fusion document `Test v2`.
- `fusion_mcp_execute` ran a read-only script inside Fusion.
- Fusion reported version `2703.1.11`.
- The installed add-in emitted `Feature Manager:` diagnostic output.
- The defensive `ui.activeWorkspace` guard logged transition-time `InternalValidationError : pActiveEnvironment` instead of crashing.
- The palette refreshed and sent timeline updates for a four-feature test document.
- Read-only Fusion MCP timeline inspection of `Test v2` returned four accessible timeline entities: `Sketch`, `ExtrudeFeature`, `FilletFeature`, and `ShellFeature`.
- Manual test in `Test v2` passed for current intended behavior: click selection, double-click edit, inline rename, right-click roll-to, close/reopen palette, and basic document/workspace interaction.
- Removed the visible `by the original author 2020` footer from the palette.
- A palette startup regression was found after removing the footer: the embedded page could miss its `ready` bootstrap and remain blank or stuck around the loading state. The fix adds a Python-side initial palette refresh through a Fusion custom event, while keeping diagnostics disabled by default so Fusion MCP structured reads are not polluted.
- After stopping and restarting the add-in, Fusion loaded the patched module with `initial_palette_refresh_handler`, `html_ready=True`, and a visible populated palette.
- Added initial vertical history marker support. Fusion MCP verified that `Design.timeline.markerPosition` is readable and writable. The palette now renders the marker position and sends `setMarkerPosition` events back to Python.
- Reworked the marker interaction from browser-native HTML drag/drop to mouse-based dragging with document-level move/up handling, nearest-slot hit testing, and temporary `user-select: none` styling to reduce accidental feature-row selection while dragging.
- Fixed a direct-drag marker repaint issue where Fusion updated the native horizontal timeline and model state, but the vertical marker could remain at its old displayed position. The Python handler now returns the requested marker position after a successful set, and the HTML moves the marker optimistically after a successful `setMarkerPosition` call.
- Replaced the old right-click-to-roll-back behavior with a Feature Manager context menu. Active first-pass actions are Create Selection Set, Edit Feature, Delete, Rename, and Roll Timeline Marker Here. Other native timeline menu entries are displayed but disabled until their Fusion command behavior is mapped and tested from the palette context.
- Set the palette default/minimum width to 435 px. The context menu now has a fixed 300 px width and opens at a constant 125 px left offset with a persistent highlight on the source row, so placement no longer varies by feature-name length.
- Fixed a grouped timeline crash where `TimelineObject.index` could throw `InternalValidationError : res >= 0` during palette refresh. Marker positions are now derived from the add-in's flattened timeline order and stored on internal tree nodes instead of reading `obj.index` during render.
- Added first-pass group/folder behavior: group rows carry collapsed state from Fusion, the group disclosure control calls Fusion's `isCollapsed` setter, and group right-click menus are context-aware with Rename Group, Expand/Collapse Group, and Roll Timeline Marker Here active. Move up/down, drag into group, and delete/ungroup are still disabled until their mutation semantics are tested.
- Fixed group disclosure behavior by using a scoped child-list reference and stopping disclosure-click bubbling. Group rows now use Fusion's built-in `Neutron/UI/Base/Resources/Folder/folder.png` asset. Marker zones are de-duplicated around groups so a marker inside a group should not also render immediately outside the group. The Fusion-generated palette Close button is disabled through the palette creation options.
- Increased timeline icon render size to 20 px to better match Fusion's Browser palette. Added final-marker de-duplication for the case where the last timeline position is also the end of the last group.
- Changed group disclosure from plus/minus text to larger Browser-style right/down chevrons, and made both the chevron and folder icon toggle group expand/collapse.
- Group disclosure now uses Fusion's existing `10x10-ArrowDown.png` and `10x10-ArrowRight.png` assets, and collapse/expand updates locally immediately before attempting to sync Fusion's group collapsed state. Project rule added: prefer Fusion-native assets and styling whenever possible.
- Added built-in timeline group management so the add-in no longer needs Timeline Manager for the core folder workflow. Multi-select right-click now exposes Group Selected Features and Ungroup Selected Groups. Group right-click now exposes Rename Group, Expand/Collapse Group, Roll Timeline Marker Here, and Ungroup. Grouping is intentionally limited to two or more contiguous, non-group, top-level timeline items; non-contiguous selections show an error dialog. Ungroup uses Fusion's `TimelineGroup.deleteMe(False)` to remove only the group while keeping its contents.
- Group drag/reorder now collapses an expanded group before calling Fusion reorder APIs, matching the documented Fusion limitation that expanded groups cannot be reordered directly.
- Reworked the Feature Manager right-click menus toward native Fusion timeline parity. Menu labels now use Fusion terminology, icon slots use Fusion resource images where available, and the implemented command path covers Create Selection Set, Edit Feature, Configure, Delete, Rename, Roll Timeline Marker Here, Convert to DM Feature, Suppress/Unsuppress Features, Find in Browser, Find in Window, Create Group, and Ungroup. Fusion MCP confirmed the native command IDs used by the menu are present in the running Fusion session.
- Transparent palette mode is now the current release-candidate design. Empty palette areas show the Fusion canvas below, while feature names, group rows, and marker controls remain interactive. Feature text uses a floating high-contrast treatment, selected/hovered rows highlight only the icon/name chip, and the history marker highlights its foreground line/handle instead of painting a full-width background band.
- Fixed a palette-side `KeyError: None` crash introduced by the icon/name wrapper: inline rename handlers now locate the containing `.feature` row with `closest('.feature')` instead of assuming the name element's direct parent is the row.
- Feature Manager selection is cleared when the timeline marker position changes, preventing stale highlighted rows after rollback or roll-forward operations.
- Fusion MCP release-candidate smoke check on `Test v4` confirmed Fusion `2703.1.11`, one active modified saved document, visible palette `FEATURE MANAGER`, `palette.isTransparent=True`, left docking state, width `435`, active design timeline count `5`, and marker position `5`.

The workspace copy and installed add-in copy both have the defensive `ui.activeWorkspace` crash fix.

## Still Needs Focused Fusion Testing

The following behaviors still need focused testing:

- Feature image contrast and exact asset parity against the native Browser palette.
- Primitive feature selection/edit behavior, especially `BoxFeature`, `CylinderFeature`, and similar feature objects inside components.
- Manual drag testing for the vertical history marker after add-in stop/start, including confirming that the vertical marker, native horizontal marker, and model rollback state stay synchronized.
- Manual testing for the Feature Manager context menu, especially Delete and Create Selection Set, because these execute Fusion commands after selecting the feature from the palette.
- Manual testing for built-in Fusion timeline group actions after add-in restart: create contiguous group, reject non-contiguous group, group rename, group expand/collapse, group drag/reorder, and ungroup while keeping contents.
- Manual testing for right-click context-menu parity: single feature, multi-feature, and group menus; command execution for Configure, Convert to DM Feature, Suppress/Unsuppress, Find in Browser, and Find in Window; icon appearance versus the native horizontal timeline.
- Timeline population across several parametric models.
- Performance on larger timelines.

## Suspected Limitations

The Fusion API may not expose enough timeline control to fully replace the native bottom timeline. Drag reordering, deep dependency visualization, and exact SolidWorks-style FeatureManager behavior should be treated as investigation items rather than assumed capabilities.

Feature icons and edit command mappings depend on Fusion resource paths and command ids, which may vary by Fusion version.

## Recommended Next Milestone

Run the manual verification checklist against the installed add-in, record each runtime failure or degraded behavior here, then triage Phase 1 bug debt before adding major new UI behavior.
