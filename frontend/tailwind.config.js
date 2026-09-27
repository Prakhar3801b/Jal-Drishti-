/**
 * Design tokens for JalDrishti.
 *
 * Two palettes live here and they must not be confused:
 *
 *   `saffron` / `indiagreen` / `chakra` are the *identity* colours, taken from the
 *   national flag (IS 1:1968 saffron #FF9933 and green #138808, plus the chakra's
 *   navy #000080) and used for chrome, headings and the masthead.
 *
 *   `risk` is the *semantic* scale, taken from IMD's operational four-colour
 *   warning convention. These are never used decoratively — if something is
 *   orange in this app it means IMD Orange, "be prepared".
 *
 * Keeping them separate is what stops a saffron-heavy government aesthetic from
 * accidentally reading as a nationwide flood warning.
 *
 * Theme: light. White surfaces, navy text, saffron accents - the visual register
 * of Indian public-service portals. The `ink` scale keeps its semantic roles
 * (950 = page, 900 = panel, 100 = strongest text) so components did not need to
 * be rewritten when the theme moved from dark to light; only the values flipped.
 * Accent shades used *as text* (300-level) are deepened to pass WCAG AA on white.
 */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        saffron: {
          50: '#FFF6EF',
          100: '#FFE9D9',
          200: '#B8420A', // text on white (hover)
          300: '#C94E0C', // text on white
          400: '#E35F12',
          500: '#F26A1B', // primary saffron
          600: '#D9560E',
          700: '#B3450A',
          800: '#8A3508',
          900: '#5C2305',
        },
        indiagreen: {
          300: '#0B7A3E', // text on white
          400: '#0E8A45',
          500: '#046A38', // flag green
          600: '#03532C',
          700: '#023B1F',
        },
        chakra: {
          300: '#1E3A8A',
          400: '#172E6E',
          500: '#0B2A5B', // government navy
          600: '#081F45',
        },
        navy: {
          50: '#EEF3FA',
          100: '#DCE6F4',
          500: '#1B3A6B',
          600: '#142D55',
          700: '#0E2242',
          800: '#0A1932',
        },
        risk: {
          green: '#0B8A3D',
          yellow: '#C99700', // IMD yellow, darkened enough to read as text on white
          orange: '#E4701E',
          red: '#C1121F',
        },
        ink: {
          950: '#F3F5F8', // page
          900: '#FFFFFF', // panel
          850: '#F8FAFC', // inset / input
          800: '#EEF2F6', // hover, bar track
          750: '#E5EAF0',
          700: '#D8DFE7', // borders
          600: '#B4BFCC',
          500: '#6E7C8D', // kicker
          400: '#526071', // secondary text
          300: '#3A4757',
          200: '#243142',
          100: '#0F1A2A', // primary text
        },
      },
      fontFamily: {
        sans: ['Inter', 'Segoe UI', 'system-ui', 'sans-serif'],
        devanagari: ['Noto Sans Devanagari', 'Nirmala UI', 'Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'Cascadia Code', 'Consolas', 'monospace'],
      },
      boxShadow: {
        panel: '0 1px 2px rgba(15,26,42,0.06), 0 8px 24px -16px rgba(15,26,42,0.18)',
        glow: '0 0 0 1px rgba(242,106,27,0.35), 0 6px 20px -8px rgba(242,106,27,0.45)',
      },
      keyframes: {
        'pulse-ring': {
          '0%': { transform: 'scale(0.85)', opacity: '0.7' },
          '70%': { transform: 'scale(1.9)', opacity: '0' },
          '100%': { transform: 'scale(1.9)', opacity: '0' },
        },
        ticker: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        'chakra-spin': {
          from: { transform: 'rotate(0deg)' },
          to: { transform: 'rotate(360deg)' },
        },
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'sheen': {
          '0%': { transform: 'translateX(-120%)' },
          '100%': { transform: 'translateX(220%)' },
        },
      },
      animation: {
        'pulse-ring': 'pulse-ring 2.4s cubic-bezier(0.2,0.6,0.35,1) infinite',
        ticker: 'ticker 48s linear infinite',
        'chakra-spin': 'chakra-spin 9s linear infinite',
        'fade-up': 'fade-up 0.32s ease-out both',
        sheen: 'sheen 2.2s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
