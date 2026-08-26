---
name: myknow
description: An image-first local reference workbench for collecting, reviewing, sorting, and selectively enriching personal knowledge.
colors:
  accent-light: "#2867d8"
  accent-dark: "#68a2ff"
  canvas-light: "#f5f6f7"
  canvas-dark: "#1c1f24"
  rail-light: "#eef0f2"
  rail-dark: "#22262c"
  panel-light: "#ffffff"
  panel-dark: "#252930"
  surface-light: "#eceff2"
  surface-dark: "#30353d"
  surface-strong-light: "#ffffff"
  surface-strong-dark: "#383e47"
  text-light: "#17191d"
  text-dark: "#f5f7fa"
  muted-light: "#505862"
  muted-dark: "#c7ced7"
  dim-light: "#737d88"
  dim-dark: "#99a4b1"
  extension-brand: "#202830"
  extension-primary: "#2867d8"
  extension-primary-dark: "#68a2ff"
  extension-muted: "#aebbc5"
  extension-ink: "#0d1b33"
  image: "#5aa9d6"
  video: "#d4778b"
  document: "#d49c55"
  webpage: "#63a985"
  danger-light: "#ad3f47"
  danger-dark: "#ff9693"
  success-light: "#176e50"
  success-dark: "#72c9a7"
typography:
  display:
    fontFamily: '"Muse Sans", "MiSans", "Microsoft YaHei UI", sans-serif'
    fontSize: "clamp(27px, 2.1vw, 32px)"
    fontWeight: 650
    lineHeight: 1.12
    letterSpacing: "-0.025em"
  heading:
    fontFamily: '"Muse Sans", "MiSans", "Microsoft YaHei UI", sans-serif'
    fontSize: "17px-21px"
    fontWeight: 620
    lineHeight: 1.35
    letterSpacing: "-0.015em"
  title:
    fontFamily: '"Muse Sans", "MiSans", "Microsoft YaHei UI", sans-serif'
    fontSize: "14px-15px"
    fontWeight: 590
    lineHeight: 1.42
    letterSpacing: "-0.01em"
  body:
    fontFamily: '"Muse Sans", "MiSans", "Microsoft YaHei UI", sans-serif'
    fontSize: "12px-13px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  label:
    fontFamily: '"Muse Sans", "MiSans", "Microsoft YaHei UI", sans-serif'
    fontSize: "10.5px-11.5px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
rounded:
  micro: "2px"
  tiny: "3px"
  soft: "4px"
  compact: "5px"
  tab: "6px"
  control: "8px"
  icon: "9px"
  card: "11px"
  capsule: "12px"
  panel: "14px"
spacing:
  micro: "4px"
  xs: "6px"
  sm: "9px"
  md: "13px"
  lg: "18px"
  xl: "24px"
---

# myknow Design System

## North Star: Atelier Index

myknow is a visual reference index used for long browsing and organization sessions. It should feel like a confident desktop image tool, not a chatbot, marketing page, or generic AI dashboard.

The interface is readable before it is decorative. Character comes from MiSans typography, confident contrast, material thumbnails, folder previews, a working color wheel, direct sorting, and clear interaction feedback. AI remains an optional processing tool and does not own the visual identity.

## Use Scene

A user sits at a desktop in mixed indoor light and reviews dozens or hundreds of images at once. Light mode must remain crisp without becoming washed out. Dark mode must reduce glare without flattening the hierarchy. The browser extension may appear over any website, so its in-page capture panel uses a stable high-contrast dark surface.

## Color Strategy

The main application uses cool neutral planes and one clear cobalt action color:

- Accent: #2867d8 in light mode and #68a2ff in dark mode.
- Light canvas: #f5f6f7.
- Light panel: #ffffff.
- Light primary text: #17191d.
- Light secondary text: #505862.
- Dark canvas: #1c1f24.
- Dark panel: #252930.
- Dark primary text: #f5f7fa.
- Dark secondary text: #c7ced7.

Media type colors remain small semantic signals:

- Image blue: #5aa9d6.
- Video rose: #d4778b.
- Document amber: #d49c55.
- Web green: #63a985.

The extension mark uses archive navy #202830 with white stacked reference sheets. The extension primary action uses #2867d8, while its persistent in-page surface stays dark enough to work over unknown websites.

## Typography

Muse Sans is an application alias for the locally installed MiSans family. Microsoft YaHei UI is the Chinese fallback. The same font family is used by the main application, extension popup, and in-page capture tray.

- Workspace display: 27px to 32px, weight 650.
- Inspector and panel heading: 17px to 21px, weight 620.
- Material title: 14px to 15px, weight 590.
- Body: 12px to 13px, weight 400.
- Labels and compact metadata: 10.5px to 11.5px, weight 600.

No visible operational text should fall below 10.5px. The primary library, folder, filter, and card labels should normally be 12px or larger.

## Layout

Desktop uses:

- 52px application module bar.
- 224px navigation rail.
- Flexible image-first material workspace with a 600px minimum.
- 336px focused inspector, so summaries remain readable without overpowering the gallery.

At 1480px, the gallery reduces to three comfortable columns. At 1240px, the inspector stacks below a two-column rail and workspace layout without reserving a ghost third column. At 700px, the application becomes a single flow and the navigation rail compacts into one 58px horizontally scrollable row.

## Gallery and Index

The view switch communicates intent:

- Gallery: large image previews, title, classification, color sample, and date. Source, summary, and tags move to the inspector.
- Index: denser cards for scanning more references at once.

Image cards use analyzed thumbnail dimensions to preserve a useful aspect ratio between 0.55 and 2.05. This range covers common 9:16 portraits and wide page captures without shrinking the media stage away from the gallery column. Cards do not crop every reference into the same generic rectangle.

Gallery columns are width-driven rather than capped at a fixed count. Wider canvases gain more image columns instead of producing oversized cards or unused space. The gallery does not display a persistent “double-click to view” badge over the artwork; double-click remains available as a quiet shortcut, alongside the explicit inspector and context-menu actions.

The full image viewer remains the close-reading surface. Double-click opens it. Clicking outside, using the close control, choosing return, or pressing Escape exits it.

## Color Wheel

The color wheel is a deliberate user filter, independent of automatic color labels.

- The conic hue wheel supports pointer dragging and keyboard arrow adjustment.
- A native exact-color input is available.
- Common color families remain quick presets.
- Color range supports close, moderate, and broad matching.
- Where supported, EyeDropper offers screen color sampling.
- Exact colors are matched against every saved palette entry using perceptual Lab distance.

## Browser Capture

The browser extension shares MiSans, the archive-sheet mark, workbench blue, the same radius logic, and the same button feedback.

- Popup: fixed light surface with dark text and a blue primary capture action.
- In-page capture tray: stable dark surface that remains readable over both light and dark websites.
- Persistent capsule: fixed near the right viewport edge, never follows the pointer, and saves the current page with one direct click.
- The capsule's secondary arrow opens folder choice, hovered-media capture, and the material-library entry without turning the website into a toolbar.
- The capsule always exposes a small close control. Closing persists across page loads; the popup provides the equally visible recovery switch.
- Drag mode has no transform entrance animation because pointer-relative movement must remain stable.
- Hold and shortcut modes may use one 260ms entrance.
- The extension toolbar uses the archive-sheet mark at 16, 32, 48, and 128px.
- Primary mobile commands use a 44px minimum target. Gallery direct actions use 40px targets; color swatches use 34px targets. The extension popup restore switch uses a 44px by 40px hit area, and the floating capsule close control uses a 30px hit area without enlarging the capsule itself.

## Shape and Depth

The radius scale is:

- 2px to 4px for tiny internal marks and directional glyphs.
- 5px to 6px for chips and compact tabs.
- 8px to 9px for standard controls and icon containers.
- 11px to 12px for capture capsules and small grouped controls.
- 14px for floating panels and popovers.

Cards use one soft shadow only during hover or selection. Resting hierarchy comes from contrast and borders. Focus rings use the workbench blue at three-pixel visual width.

## Motion

Motion communicates hierarchy, feedback, and state:

- Application entry: module bar, rail, header, controls, and inspector enter in sequence over 360ms to 580ms.
- Material refresh: up to the first 18 cards enter with 24px travel, slight scale, blur removal, and a 35ms stagger.
- Panels: clip open over 500ms.
- Color wheel: popover enters over 220ms.
- Theme switch: the new theme reveals from the theme control over 360ms when View Transitions are supported.
- Buttons depress to 98% on press.

All motion honors prefers-reduced-motion. Content remains visible and functional when motion is disabled.

## Contrast Rules

- Light primary text uses #17191d on white.
- Light secondary text uses #505862.
- Light dim text uses #737d88 only for nonessential metadata.
- Dark primary text uses #f5f7fa.
- Dark secondary text uses #c7ced7.
- Placeholders use the dim token and remain fully opaque.
- Capture guide icons in light mode use dark blue on #d8edf5, never pale text on white.

## Do

- Let real material imagery carry most visual color.
- Keep primary browsing labels at 12px or larger.
- Put explanations in the inspector and keep the gallery direct.
- Use one noticeable authored motion sequence plus local feedback.
- Keep the extension and main application recognizably related.
- Preserve click, keyboard, context-menu, and drag alternatives.

## Do Not

- Do not use purple AI gradients, glowing orbs, assistant mascots, or prompt-first compositions.
- Do not show source, summary, tags, type, date, and classification with equal visual weight in gallery mode.
- Do not use pale grey text on white or dark grey text on charcoal.
- Do not animate drag-panel position or size.
- Do not make automatic AI labels the only way to choose a color.
