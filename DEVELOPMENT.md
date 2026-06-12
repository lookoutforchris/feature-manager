# Development

## Clone

Clone the repository:

```powershell
git clone https://github.com/lookoutforchris/feature-manager.git
```

Expected working files include `FeatureManager.py`, `FeatureManager.manifest`, `palette.html`, `resources/`, and `featuremanagerlib/`.

## VS Code and Codex

Use the checked-in VS Code workspace file:

```powershell
code .\feature-manager.code-workspace
```

Codex can continue work from either the desktop app or the VS Code extension. If resuming an existing Codex session in VS Code works, prefer that because it preserves discussion context. If a fresh VS Code thread is needed, start it from the repository root so Codex loads `AGENTS.md`, `.codex/config.toml`, and the planning documents.

For VS Code Codex MCP access, make sure:

1. Fusion is running.
2. Fusion preferences have **Fusion MCP Server** enabled.
3. The Fusion MCP URL is `http://127.0.0.1:27182/mcp`.
4. The project is trusted by Codex so project `.codex/config.toml` is loaded.
5. A smoke check with `fusion_mcp_read` can list the active Fusion document.

Codex MCP configuration is project-scoped in `.codex/config.toml`; it is not `.mcp.json`.

## Install in Fusion

For the current Windows Fusion setup, install or copy this folder to:

```text
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\FeatureManager
```

Fusion expects the add-in folder name to match the manifest location. Keep `FeatureManager.manifest` beside `FeatureManager.py`.

## Deploy Workspace Changes

For the current Windows install path, sync the source files from this workspace into Fusion's AddIns folder:

```powershell
.\tools\Sync-InstalledAddIn.ps1
```

Preview the copy operations first:

```powershell
.\tools\Sync-InstalledAddIn.ps1 -WhatIf
```

The sync script copies only add-in runtime files: `FeatureManager.py`, `FeatureManager.manifest`, `palette.html`, `timeline_overlay.ps1`, `resources/`, and `featuremanagerlib/`. It does not copy planning docs, `.git`, `.codex`, or the installed add-in's `settings.json`.

## Run and Stop

Open Fusion, then use `Shift+S` to open **Scripts and Add-Ins**. On the **Add-Ins** tab, select `FeatureManager` and press **Run**. Use **Stop** from the same dialog to unload it.

The add-in registers **Toggle Feature Manager** and **Toggle Horizontal Timeline** commands under the Fusion **File > View** menu. If the add-in setting is enabled and Fusion startup is complete, startup attempts to show the palette automatically. On Windows, **Toggle Horizontal Timeline** starts a Fusion-owned WPF bottom bar from `timeline_overlay.ps1`; this visually covers the native bottom timeline without disabling parametric history.

The bottom bar currently provides timeline transport controls, feature type filters, a feature search field, and timeline status text. The WPF helper writes JSON action files under `overlay-actions/`; the Fusion Python add-in drains those actions through the existing refresh event and remains the only code that calls Fusion APIs. The Python add-in writes `overlay_state.json` so the WPF helper can display marker, timeline count, suppressed count, search, and filter state.

## Event Flow

`run(context)` initializes `app` and `ui`, registers the toggle command, adds the View menu control, and subscribes to command, document, and workspace events.

`show_palette()` creates the left-docked transparent HTML palette from `palette.html` and attaches `incomingFromHTML` and `closed` handlers. `palette_incoming_from_html_handler()` receives browser-side actions such as `ready`, rename, select, edit, marker movement, reorder, group, ungroup, suppress/unsuppress, and native command execution.

`invalidate()` reads the Fusion timeline through `featuremanagerlib.timeline.get_timeline()`, converts timeline objects into palette data, and sends `setTimeline` to the HTML palette.

`document_activated_handler()` and `workspace_activated_handler()` keep the palette synchronized with Fusion Design workspace activation. Current Fusion versions can throw while reading `ui.activeWorkspace` during transitions, so active workspace access must remain defensive.

## Diagnostics

This milestone has lightweight diagnostics through `debug_log()` in `FeatureManager.py`. Diagnostics are gated by `DEBUG_LOGGING = False` by default because Fusion MCP read tools parse script output as JSON, and unrelated add-in `print()` output can corrupt those responses.

When temporarily debugging add-in lifecycle behavior, set `DEBUG_LOGGING = True` in `FeatureManager.py`, deploy to the installed add-in folder, and restart the add-in. Turn it back off before using Fusion MCP read tools for structured inspection.

To gather errors, copy Fusion add-in error dialogs with `Ctrl+C` when shown. Also check Fusion's text command/output area for `Feature Manager:` diagnostic lines.

## Verification

Static syntax check outside Fusion:

```powershell
python -m py_compile .\FeatureManager.py
```

Runtime verification requires Fusion:

1. Start Fusion.
2. Load the add-in from **Scripts and Add-Ins**.
3. Confirm no startup error is shown.
4. Open a parametric Design document.
5. Toggle the Feature Manager palette.
6. Confirm timeline entries populate and interactions can be exercised.
7. Confirm transparent empty areas show the Fusion canvas below, while row text, context menus, and marker controls remain readable and interactive.
8. Use **File > View > Toggle Horizontal Timeline** and confirm the bottom bar appears, follows the Fusion window, does not cover other apps, and can move the timeline marker with previous/end controls.

Fusion MCP smoke check:

1. Make sure Fusion is running with the Fusion MCP server enabled.
2. Use `fusion_mcp_read` with `queryType=document` and `operation=open`.
3. Use `fusion_mcp_execute` for read-only scripts that print `app.version` and the active document name.
