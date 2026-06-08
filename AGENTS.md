# AGENTS.md

## Project

This repository is Feature Manager, a working fork of `original-author/VerticalTimeline`: a left-side, SolidWorks-style feature/history manager for Autodesk Fusion.

Do not start with a rewrite. Stabilize the existing add-in first, document current Fusion API behavior, then refactor toward a richer Feature Manager UI.

## Environment

- Workspace: local project checkout
- Installed Fusion add-in: `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\VerticalTimeline`
- Fusion MCP endpoint: `http://127.0.0.1:27182/mcp`
- Local editor: VS Code
- Shell: PowerShell on Windows
- Additional tools: MSYS2 under `C:\dev`

## Architecture

- Fusion integration is Python in `VerticalTimeline.py`.
- UI is a Fusion HTML palette in `palette.html`.
- Shared helper code is in the `featuremanagerlib/` submodule.
- Manifest is `VerticalTimeline.manifest`.
- Current runtime diagnostics use `print()` lines prefixed with `Feature Manager:`.

## Development Rules

- Keep changes small and reviewable.
- Preserve existing behavior unless it is clearly broken.
- Do not redesign the UI until stabilization and requirements notes are current.
- Prefer existing Fusion assets, icons, colors, spacing, and interaction patterns whenever possible. The add-in should look and feel like it belongs in Fusion's default interface; only create custom assets when no suitable Fusion-native asset exists.
- Prefer Fusion MCP for runtime inspection and test loops.
- Do not save or close Fusion documents unless the user explicitly asks.
- Do not assume a Fusion API capability exists; test it or document uncertainty.
- If a change must also affect the installed add-in folder, say so and apply it deliberately.
- Use `apply_patch` for manual source edits.

## Verification

Static syntax check:

```powershell
python -m py_compile .\VerticalTimeline.py
```

Fusion runtime checks should use MCP when available:

- Read open documents with `fusion_mcp_read`.
- Run read-only scripts with `fusion_mcp_execute`.
- Create disposable test geometry only when explicitly useful for the current task.

Manual Fusion checks:

- Stop/start the add-in from **Scripts and Add-Ins**.
- Confirm palette creation and timeline population.
- Test click select, double-click edit, inline rename, group collapse, and right-click roll-to.

## Planning Documents

- `ROADMAP.md`: phased engineering plan.
- `REQUIREMENTS_NOTES.md`: human review and brainstorming for SolidWorks-style FeatureManager behavior.
- `CURRENT_STATUS.md`: current behavior, known failures, and tested limitations.
- `DEVELOPMENT.md`: setup and diagnostic notes.

## Review Priorities

When reviewing changes, prioritize:

- Fusion runtime crashes.
- Broken document/workspace transition handling.
- Data loss risks from rename/edit/roll-to operations.
- Regressions in existing palette actions.
- Performance risks for large timelines.
- Missing or misleading documentation about Fusion API limitations.
