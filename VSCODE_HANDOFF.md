# VS Code Handoff

Use this repository as the VS Code workspace:

```powershell
code C:\dev\projects\feature-manager
```

## Codex Extension

The Codex IDE extension uses the same agent and shared Codex configuration as the CLI/app. Project instructions come from `AGENTS.md`. Project MCP configuration is in `.codex/config.toml`.

Before starting work in VS Code:

1. Open `C:\dev\projects\feature-manager`.
2. Make sure the project is trusted by Codex so `.codex/config.toml` is loaded.
3. Make sure Fusion is running.
4. In Fusion preferences, keep **Fusion MCP Server** enabled.
5. Confirm the Fusion MCP URL is `http://127.0.0.1:27182/mcp`.
6. Start a Codex thread from the VS Code sidebar.
7. Ask Codex to list MCP tools or run a read-only Fusion check.

Expected Fusion MCP tools:

- `fusion_mcp_read`
- `fusion_mcp_execute`
- `fusion_mcp_update`
- `fusion_mcp_electronics_read`

## Recommended VS Code Usage

Use VS Code for:

- Reviewing diffs.
- Editing Python, HTML, CSS, and JavaScript.
- Markdown planning and requirement review.
- Git status and commits.
- Running local syntax checks.

Do not use local Python execution as the runtime source of truth for Fusion behavior. The `adsk` modules exist inside Fusion, so runtime verification belongs in Fusion through MCP.

## Useful Commands

Static syntax check:

```powershell
python -m py_compile .\VerticalTimeline.py
```

Check repo status:

```powershell
git status --short
```

Open installed add-in folder:

```powershell
explorer "C:\Users\Chris\AppData\Roaming\Autodesk\Autodesk Fusion 360\API\AddIns\VerticalTimeline"
```

## Current Working Context

The workspace copy and installed Fusion add-in copy both have the defensive `ui.activeWorkspace` crash fix. The installed add-in has been verified through Fusion MCP to run and emit `Vertical Timeline:` diagnostic output.

Next work should generally update the workspace first, verify with syntax checks, then deliberately copy or patch the installed add-in folder for Fusion runtime testing.

