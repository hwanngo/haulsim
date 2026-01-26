# CAT Design System

The "CAT" design system: a utilitarian, high-contrast enterprise interface with
industrial branding and minimal ornament. These tokens are the source of the
Chakra theme in `frontend/src/system.ts`.

## Overview

cat.com presents a practical, industrial, and globally oriented interface with very little decorative softness. The tone is professional and utilitarian, aimed at users who need to choose a region and language quickly with minimal cognitive load. Visual emphasis comes from strong contrast, a bright CAT yellow call-to-action, and clean centered card layout over a faint world-map backdrop.

## Table of Contents

1. [Design Tokens](#1-design-tokens)
2. [Colors](#2-colors)
3. [Typography](#3-typography)
4. [Layout](#4-layout)
5. [Elevation & Depth](#5-elevation--depth)
6. [Shapes](#6-shapes)
7. [Components](#7-components)
8. [Do's and Don'ts](#8-dos-and-donts)

## 1. Design Tokens

```yaml
version: alpha
name: CAT
description: A utilitarian, high-contrast enterprise selector with industrial branding and minimal ornament.
colors:
  primary: "#FFCD11"
  secondary: "#000000"
  tertiary: "#0067B8"
  neutral: "#FFFFFF"
  surface: "#FFFFFF"
  on-surface: "#000000"
  border: "#E5E7EB"
  border-strong: "#B18D00"
  muted: "#5F6675"
  overlay: "#0000004D"
typography:
  headline-display:
    fontFamily: "Roboto Condensed Bold"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "0px"
  headline-lg:
    fontFamily: "Roboto Condensed Bold"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: "20.3px"
    letterSpacing: "0px"
  headline-md:
    fontFamily: "Roboto Condensed Bold"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: "20.3px"
    letterSpacing: "0px"
  headline-sm:
    fontFamily: "Arial"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: "20.3px"
    letterSpacing: "0px"
  body-lg:
    fontFamily: "Noto Sans Regular"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: "24px"
    letterSpacing: "0px"
  body-md:
    fontFamily: "Noto Sans Regular"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: "24px"
    letterSpacing: "0px"
  body-sm:
    fontFamily: "Noto Sans Regular"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: "20px"
    letterSpacing: "0px"
  label-lg:
    fontFamily: "Noto Sans Semibold"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: "20px"
    letterSpacing: "0px"
  label-md:
    fontFamily: "Arial"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: "20px"
    letterSpacing: "0px"
  label-sm:
    fontFamily: "Arial"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: "16px"
    letterSpacing: "0px"
  caption:
    fontFamily: "Arial"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: "16px"
    letterSpacing: "0px"
rounded:
  none: 0px
  sm: 2px
  md: 4px
  lg: 8px
  xl: 12px
  full: 9999px
spacing:
  xs: 4px
  sm: 16px
  md: 24px
  lg: 44px
  xl: 106px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.secondary}"
    typography: "{typography.label-lg}"
    rounded: "{rounded.md}"
    padding: "9px 44px"
    height: "39px"
    width: "305px"
  button-secondary:
    backgroundColor: "{colors.neutral}"
    textColor: "{colors.secondary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: "9px 44px"
    height: "39px"
    width: "305px"
  button-link:
    backgroundColor: "transparent"
    textColor: "{colors.tertiary}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.none}"
    padding: "0px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: "16px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body-md}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
  select:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    typography: "{typography.body-md}"
    rounded: "{rounded.sm}"
    padding: "10px 12px"
```

## 2. Colors

- **Primary (#FFCD11):** The signature CAT yellow used for the main call-to-action and brand emphasis. It feels energetic, machinery-like, and unmistakably industrial.
- **Secondary (#000000):** Deep black used for logos, headings, body text, and button text. It provides the sharp contrast that gives the interface its authoritative, no-nonsense character.
- **Tertiary (#0067B8):** A standard link blue reserved for secondary interaction patterns and reference links. It reads as functional rather than decorative.
- **Neutral / Surface (#FFFFFF):** The dominant canvas color across the page, cards, form fields, and footer-adjacent surfaces. It keeps the experience open and legible.
- **Border (#E5E7EB):** A subtle cool gray used for card and field outlines, separating controls without heavy visual weight.
- **Border Strong (#B18D00):** A deeper yellow-brown accent that supports the primary yellow button border and adds a slightly mechanical finish.
- **Muted (#5F6675):** A supporting gray for less prominent text or helper content where needed. The value was darkened from the spec's original #6B7280 to clear WCAG AA contrast (4.5:1) against the #f4f4f4 page background.
- **Overlay (#0000004D):** A soft translucent black shadow/overlay tone that helps depth without introducing rich elevation effects.

## 3. Typography

The system relies on a compact, pragmatic typographic stack. Headlines use Roboto Condensed Bold, which gives the page a tall, compressed, industrial feel; the primary heading is bold and tight, with almost no letter spacing. Supporting headings may fall back to Arial in some contexts, while body and label text use Noto Sans for clarity and broad readability.

Use `headline-lg` and `headline-md` for centered section titles and prominent page prompts. Use `body-md` for explanatory copy, cookie text, and form content. Use `label-lg` for button text and strong field labels, keeping the labels functional and direct rather than editorial. Uppercase is not a core system rule here, but the brand voice is terse and title-like, so short headings should remain concise and utility-driven.

## 4. Layout

The layout is centered and fixed-feeling rather than fluid editorial. A single card sits above a large, pale background map, with generous negative space that makes the form easy to scan. Vertical spacing follows a simple rhythm based on `xs`, `sm`, `md`, `lg`, and `xl`, with noticeable breathing room between the logo, title, select fields, and CTA.

Section and card padding should stay disciplined: 16px inside cards, 24px or more between major blocks, and ample outer whitespace around the main selector panel. Controls are wide and aligned for fast selection, with a clear minimum width behavior that supports a desktop-first experience. The footer and cookie notice occupy separated bands, reinforcing task hierarchy over visual decoration.

## 5. Elevation & Depth

Depth is handled sparingly and mostly through soft shadows and layering rather than strong 3D effects. The central card uses a subtle shadow to float above the map background, while the page itself remains largely flat and bright. Borders are important for defining form fields and the card boundary, since the visual language avoids heavy gradients or glossy treatment.

The result is a restrained hierarchy: page background first, selector card second, and controls clearly segmented by thin borders. Shadows should stay minimal and functional, never dramatic.

## 6. Shapes

The shape language is straightforward and slightly industrial. Buttons use a small 4px radius for the primary action and a tighter 2px radius for secondary actions, while cards use a modest 8px radius for a clean container feel. Overall, the system favors crisp edges and near-rectilinear geometry, which supports the brand's utilitarian character.

Avoid overly pill-shaped controls except where functionally necessary. The interface should feel engineered, not playful.

## 7. Components

Buttons are the most branded element in the system. `button-primary` is a wide yellow CTA with black text, a thin dark border, and a compact 39px height; it should remain the strongest visual accent on the page. Use `button-secondary` for neutral actions such as cookie settings: white background, black border, black text, and a slightly sharper 2px radius. `button-link` should appear text-only, with no container chrome and blue link color.

Cards should use `card` as a clean white container with a subtle border and 16px padding. Keep card content centered when used in the selector flow, and let the card shadow do the work rather than adding internal separators.

Inputs and selects should feel simple and utilitarian: white backgrounds, thin gray borders, modest padding, and compact rounded corners. Labels should sit close to fields and remain bold enough to scan quickly, but not overpower the values. Dropdown arrows should be understated and monochrome.

Lists and footer navigation should be treated as terse utility navigation, with small uppercase or compact labels and tight horizontal spacing. Cookie notices should prioritize readability over polish, using body-sized text and clearly differentiated actions. Keep any additional controls consistent with the same border-first, low-chrome approach.

The AMT Cycle Workbench implements three panel-level components. `ImportButton` (`frontend/src/components/ImportButton.tsx`) is a drag-and-drop ZIP uploader with SSE progress tracking. `ExportPanel` (`frontend/src/components/ExportPanel.tsx`) drives the database-to-simulation export flow: site and material pickers, export-type selection, collapsible advanced settings, SSE progress, and — once an export completes and load zones are detected — a collapsible per-zone material section that lets users override the site-wide material per load zone. Both panels share `ExportToggle` (`frontend/src/components/ExportToggle.tsx`), a reusable CAT-styled switch row extracted to remove duplication: it renders a labelled card with a visual toggle, using `cat.yellow` for the checked state and `cat.yellowEdge` for the border accent.

## 8. Do's and Don'ts

- Do keep the primary CTA in CAT yellow with black text and a compact industrial feel.
- Do center the main selector card and preserve generous whitespace around it.
- Do use condensed bold typography for strong headings and Noto Sans for body copy.
- Do rely on borders and subtle shadows for hierarchy instead of heavy elevation.
- Don't introduce rounded, playful shapes or soft pastel accents.
- Don't make secondary actions compete with the yellow primary button.
- Don't overcomplicate form fields with decorative icons, gradients, or filled backgrounds.
- Don't reduce contrast in labels, buttons, or navigation; readability is essential.
