# Palette Layout Research

## Goal

Evaluate whether Fusion's native Browser palette can be stacked above the Feature Manager palette, approximating a SolidWorks-style Feature Manager area where model/browser structure is above feature history.

## Current Live Palette Findings

Fusion exposes both palettes through `ui.palettes`:

- Native Browser palette:
  - `id`: `Browser`
  - `name`: `Browser`
  - `isNative`: `True`
  - `isVisible`: `True`
  - observed `dockingState`: left
  - observed `dockingOption`: vertical-only
- Feature Manager palette:
  - `id`: `featureManager_palette`
  - `name`: `FEATURE MANAGER`
  - `isNative`: `False`
  - `isVisible`: `True`
  - observed `dockingState`: left
  - observed `dockingOption`: vertical-and-horizontal

Fusion's `Palette` API exposes `snapTo`, and `PaletteSnapOptions` includes `PaletteSnapOptionsBottom`, so a Browser-above / Feature-Manager-below arrangement may be possible without recreating the Browser.

## Preferred Direction

Prefer using Fusion's native Browser palette directly.

Reasons:

- It preserves Fusion's native assets, behavior, context menus, collapse/expand behavior, and future compatibility.
- It avoids reimplementing Browser data, visibility controls, body/component expansion state, and native commands.
- It follows the project rule to prefer Fusion-native assets and interaction patterns.

## Experiment Plan

Do this only as an explicit layout experiment, not as an automatic startup behavior yet.

1. Record current Browser and Feature Manager geometry:
   - `dockingState`
   - `width`
   - `height`
   - `left`
   - `top`
2. Try snapping Feature Manager below Browser:
   - `vertical_palette.snapTo(browser_palette, PaletteSnapOptionsBottom)`
3. Observe:
   - Does Fusion stack palettes vertically on the left?
   - Does the Browser retain its native collapse/expand behavior?
   - Does Feature Manager stay below Browser after command completion?
   - Does Fusion remember the layout after restart?
4. If snap does not work while docked, test only with explicit approval:
   - floating both palettes
   - snapping in floating state
   - restoring left docking

## Risks

- Native Browser may have special layout behavior not fully controlled by the public Palette API.
- `snapTo` may work only for floating palettes or may not persist.
- Automatic rearrangement may frustrate users who prefer their existing Fusion layout.
- Moving native palettes from an add-in can feel invasive unless it is opt-in.

## Browser Nested Inside Feature Manager

This is conceptually attractive because SolidWorks presents the model tree and feature history as one integrated manager area.

However, nesting the actual native Browser inside our HTML palette is unlikely to be available through the public Fusion API. The Browser is a native Fusion palette, not an embeddable HTML component.

Recreating the Browser inside our palette is technically possible only as a custom clone, but it is not preferred:

- It would duplicate a large amount of native Fusion behavior.
- It would be hard to keep visually and behaviorally aligned with Fusion.
- It would likely miss native context menus and state.
- It would increase maintenance risk substantially.

If we want a unified tree later, the better long-term design is a FeatureManager-style custom tree that shows selected high-value browser concepts, not a full Browser clone. That should be a separate requirements/design phase.

## Recommendation

Short term:

- Test `snapTo(Browser, Bottom)` manually/experimentally.
- If reliable, add an optional command or setting: `Stack Feature Manager Below Browser`.

Medium term:

- Keep the Browser native.
- Improve Feature Manager group/folder behavior until it feels like Fusion's Browser.

Long term:

- Consider a unified Feature Manager-style tree only after requirements are clear, and treat it as a purpose-built replacement rather than embedding Fusion's Browser.
