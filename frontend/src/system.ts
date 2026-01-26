import { createSystem, defaultConfig, defineConfig } from '@chakra-ui/react'

// "CAT" design system (see docs/design_system.md) expressed as a Chakra theme:
// CAT yellow, black ink, Roboto Condensed headings, Noto Sans body, small radii.
const config = defineConfig({
  theme: {
    tokens: {
      colors: {
        cat: {
          yellow: { value: '#FFCD11' },
          yellowEdge: { value: '#B18D00' }, // border-strong
        },
        ink: { value: '#000000' }, // on-surface / secondary
        link: { value: '#0067B8' }, // tertiary
        line: { value: '#E5E7EB' }, // border
        // Muted text. Darkened from the spec #6B7280 so it clears WCAG AA (4.5:1)
        // even on the #f4f4f4 page background (the lighter #6B7280 measured 4.40:1).
        muted: { value: '#5F6675' },
        // Modal/scrim overlay (design_system.md "overlay" token): a soft
        // translucent black for depth, in keeping with the system's minimal,
        // non-glossy elevation language.
        overlay: { value: '#0000004D' },
      },
      fonts: {
        heading: { value: "'Roboto Condensed', 'Arial Narrow', sans-serif" },
        body: { value: "'Noto Sans', Arial, sans-serif" },
      },
      // Small, industrial radii (override Chakra defaults).
      radii: {
        sm: { value: '2px' },
        md: { value: '4px' },
        lg: { value: '8px' },
        xl: { value: '12px' },
      },
    },
  },
  globalCss: {
    'html, body, #root': {
      bg: '#f4f4f4',
      color: 'ink',
      fontFamily: 'body',
    },
    // NOTE: the keyboard focus ring lives in index.css as UNLAYERED CSS so it
    // wins over Chakra's @layer-scoped 1px default (cascade layers always lose
    // to unlayered rules).
  },
})

export const system = createSystem(defaultConfig, config)
