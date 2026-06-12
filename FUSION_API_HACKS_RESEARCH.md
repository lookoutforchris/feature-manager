# Fusion API Hacks and Workarounds Research

Research date: 2026-06-09

This note captures credible public leads for Fusion API workarounds relevant to Feature Manager. Treat these as investigation leads, not guaranteed design decisions. Prefer Autodesk API documentation and Fusion MCP verification before implementing.

## Palette as the Correct UI Boundary

Autodesk's palette documentation supports the current Python plus HTML palette architecture. Palettes are long-lived UI surfaces, can remain visible while users interact with Fusion, can be docked to Fusion edges and other palettes, and communicate with add-in Python through `sendInfoToHTML` / `adsk.fusionSendData`.

Important constraints:

- Palette JavaScript cannot call the Fusion API directly.
- Browser-to-Python communication must go through palette events.
- Fusion can delete palettes when switching workspaces; invalid palette references must be recreated.
- The newer Qt browser path changes `adsk.fusionSendData` return behavior compared with the older CEF browser.

Source: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Palettes_UM.htm

## Palette Developer Tools

Autodesk documents that browser developer tools are controlled by a Fusion preference. Older forum snippets also mention `devoptions.webdeveloperextras /on` and the `NEUTRON_WEB_DEVELOPER_EXTRAS` environment variable as possible debugging workarounds, but verify current Fusion behavior before relying on them.

Source: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Palettes_UM.htm

## Timeline Marker and Rollback

`TimelineObject.rollTo(rollBefore)` is the official way to reposition the timeline marker relative to a timeline object. Autodesk documents that it fails when the object is a timeline group and that group is expanded.

Implication for Feature Manager:

- Keep the current group-aware fallback logic.
- Use `rollTo(True)` / `rollTo(False)` where possible.
- Continue supporting direct `Design.timeline.markerPosition` only after Fusion MCP verification.

Source: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/TimelineObject_rollTo.htm

## Selection Synchronization

`UserInterface.activeSelectionChanged` exists and fires when the active Select command's selection changes. Autodesk documents that it only applies to the Select command selection and does not fire while other commands are running.

Implication for Feature Manager:

- It may support partial native-selection-to-palette synchronization.
- It will not be a perfect global selection mirror during every Fusion command.
- Any selection sync feature should explicitly handle command-state limitations.

Source: https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/ActiveSelectionEvent.htm

## Timeline Group Creation

Autodesk forum examples show creating timeline groups with `design.timeline.timelineGroups.add(firstIndex, lastIndex)`, often by recording `design.timeline.markerPosition` before and after scripted work. Forum guidance notes that timeline groups cannot be nested inside timeline groups.

Implication for Feature Manager:

- Group creation from selected contiguous timeline ranges is plausible.
- Non-contiguous selection cannot map directly to one native timeline group.
- Nested logical groups in our UI may need to remain virtual if Fusion native groups cannot represent them.

Source: https://forums.autodesk.com/t5/fusion-api-and-scripts/how-to-create-timeline-groups/m-p/11598497

## Native Browser Stacking

Fusion exposes native and custom palettes through `ui.palettes`; our local MCP testing already found the native Browser palette as `id = Browser`. Autodesk palette docs say palettes can dock to edges and other palettes, and the API exposes snapping behavior.

Implication for Feature Manager:

- A Browser-above / Feature-Manager-below layout may be possible through palette snapping.
- This should stay opt-in because moving a native palette is invasive.
- Continue the experiment tracked in `PALETTE_LAYOUT_RESEARCH.md`.

Sources:

- https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Palettes_UM.htm
- `PALETTE_LAYOUT_RESEARCH.md`

## Command Dialog Positioning Limits

Forum search results indicate palette positioning is controllable, but command dialog positioning may not have a public API. Treat command-dialog placement as out of scope unless current Fusion MCP/API docs prove otherwise.

Source lead: https://forums.autodesk.com/t5/fusion-api-and-scripts-forum/the-way-to-control-command-dialog-positioning/td-p/12956032

## User Demand Signals

Public Fusion community posts repeatedly complain about timeline usability in large models and compare Fusion unfavorably to tree-based CAD systems. These are not API facts, but they support the product direction: a readable, searchable, left-side feature manager is solving a real workflow pain.

Source leads:

- https://www.reddit.com/r/Fusion360/comments/jo5eqb/is_it_possible_to_configure_f360_with_a_feature/
- https://www.reddit.com/r/Fusion360/comments/1jz49bo/fusion_timeline_what_a_mess/

## Investigation Backlog

- Verify whether `activeSelectionChanged` can map selected entities back to timeline objects reliably.
- Test `timelineGroups.add()` for selected contiguous ranges, collapsed groups, and rolled-back marker states.
- Test whether palette `snapTo(Browser, Bottom)` works while both palettes are docked left.
- Verify current Qt palette `adsk.fusionSendData` behavior in the installed Fusion version.
- Confirm whether `devoptions.webdeveloperextras /on` still enables useful palette devtools.
- Test whether direct marker writes and `rollTo()` produce identical or different event sequences.

## Native Horizontal Timeline Hide Experiment

Goal: find a reversible way to hide or visually suppress Fusion's native bottom timeline while keeping parametric history active.

### Experiment Order

1. Enumerate Fusion command definitions for timeline/history/visibility commands using Fusion MCP.
2. Enable temporary command tracing and manually interact with native timeline controls.
3. Test any credible native commands discovered by tracing.
4. If no command route exists, prototype a bottom-docked visual cover palette.
5. If that fails, inspect Windows UI Automation / child-window handles as a Windows-only experiment.
6. Avoid patching Fusion installation resources except as throwaway research.

### Current Trace Hook

`FeatureManager.py` includes an off-by-default command trace hook:

```python
TRACE_FUSION_COMMANDS = False
```

To use it:

1. Temporarily set `TRACE_FUSION_COMMANDS = True`.
2. Deploy the add-in with `.\tools\Sync-InstalledAddIn.ps1`.
3. Restart the add-in in Fusion.
4. Manually click native timeline settings, marker, playback, group, and visibility controls.
5. Copy any `Feature Manager Command Trace:` lines into this file or `CURRENT_STATUS.md`.
6. Set `TRACE_FUSION_COMMANDS = False` again before normal MCP testing.

Reason: trace output uses `print()`, and unrelated add-in output can pollute Fusion MCP structured responses.

### Result

No supported API has been found to hide only the native timeline. Disabling design history is not a suitable answer because it changes modeling behavior instead of only hiding UI.

The best current workaround is a Windows-only WPF overlay window owned by Fusion's main native window. Ownership matters: a global topmost overlay covers other applications, while a Fusion-owned, non-topmost overlay follows Fusion's stacking order and does not stay above VS Code or other foreground windows.

### Local MCP Findings

Fusion MCP test date: 2026-06-09

- Open Fusion document: `Test v4`.
- Runtime command registry search found timeline operations such as `FusionFindInTimeline`, `FusionRollCommand`, `FusionCreateGroupFeatureCommand`, `FusionCollapseGroupFeatureCommand`, `FusionRenameTimelineEntryCommand`, `FusionReorderCommand`, and `FusionTrimFeaturesCommand`.
- Runtime command registry search did not find a credible `HideTimeline`, `ShowTimeline`, or timeline visibility toggle command.
- `CloseTimlineConfigModePanel` exists, but its name suggests it closes only a configuration-mode panel and not the native bottom timeline.
- Static search of Fusion/Neutron UI command resources likewise found timeline command/tooltip references but no direct hide/show timeline command.
- `PaletteDockingStates.PaletteDockStateBottom` is available.
- A transient MCP-created palette using `PaletteDockStateBottom` succeeded:
  - id: `featureManager_timeline_cover_experiment`
  - requested height: `42`
  - Fusion-reported height after docking: `61`
  - reported docking state: `2`
- User screenshots confirmed bottom-docked palettes are placed above Fusion's native bottom timeline, leaving the native timeline visible. This makes the palette route unsuitable for hiding the horizontal timeline.
- Windows UI Automation identified native timeline elements including `Na::QtTimelineBackgroundLabel`, but no reliable public Fusion command was found for hiding that element.
- A WPF overlay placed at Fusion's bottom window bounds, with `WindowInteropHelper.Owner` set to Fusion's native HWND and `Topmost = $false`, successfully covers the native horizontal timeline without covering other applications.

### Runtime Overlay Implementation

The current implementation is:

- `FeatureManager.py` registers **Toggle Horizontal Timeline** under **File > View**.
- The command toggles the persisted setting `horizontalTimelineHidden`.
- When enabled on Windows, the add-in launches `timeline_overlay.ps1` with PowerShell in STA mode.
- `timeline_overlay.ps1` creates a borderless WPF bottom bar, owns it to Fusion's native window, and polls Fusion's bounds so the overlay follows Fusion window moves/resizes.
- The bottom bar includes begin/previous/play/next/end timeline controls, feature type filters, a feature search field, and right-aligned marker/suppression status.
- The WPF helper writes JSON action files under `overlay-actions/`; the Fusion add-in processes them on the existing refresh custom event and writes `overlay_state.json` for the helper to display.
- The release and sync scripts include `timeline_overlay.ps1`.

Revert path:

1. Use **File > View > Toggle Horizontal Timeline** again to toggle the overlay off.
2. If an orphan helper remains after an add-in crash, end the `pwsh.exe` process whose command line contains `timeline_overlay.ps1`.
3. To remove the feature from code, delete the `featureManager_hideHorizontalTimeline` command registration and remove `timeline_overlay.ps1` from sync/release packaging.
