/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: '#131315',
        surface: {
          DEFAULT: '#131315',
          dim: '#131315',
          bright: '#39393b',
          container: {
            lowest: '#0e0e10',
            low: '#1c1b1d',
            DEFAULT: '#201f22',
            high: '#2a2a2c',
            highest: '#353437',
          },
          variant: '#353437',
          tint: '#d0bcff',
        },
        'on-surface': { DEFAULT: '#e5e1e4', variant: '#cbc3d7' },
        primary: { DEFAULT: '#d0bcff', container: '#a078ff' },
        'on-primary': { DEFAULT: '#3c0091', container: '#340080' },
        secondary: { DEFAULT: '#ffb0cd', container: '#aa0266', fixed: { DEFAULT: '#ffd9e4', dim: '#ffb0cd' } },
        'on-secondary': { DEFAULT: '#640039', container: '#ffbad3' },
        tertiary: { DEFAULT: '#4cd7f6', container: '#009eb9' },
        'on-tertiary': { DEFAULT: '#003640', container: '#002f38' },
        error: { DEFAULT: '#ffb4ab', container: '#93000a' },
        outline: { DEFAULT: '#958ea0', variant: '#494454' },
        'inverse-surface': '#e5e1e4',
        'inverse-on-surface': '#313032',
        'inverse-primary': '#6d3bd7',
      },
      fontFamily: {
        sans: ['Geist', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      fontSize: {
        'display-lg': ['48px', { lineHeight: '1.1', letterSpacing: '-0.04em', fontWeight: '700' }],
        'headline-md': ['24px', { lineHeight: '32px', letterSpacing: '-0.02em', fontWeight: '600' }],
        'body-base': ['16px', { lineHeight: '24px', letterSpacing: '-0.01em', fontWeight: '400' }],
        'code-sm': ['13px', { lineHeight: '20px', fontWeight: '450' }],
        'label-caps': ['11px', { lineHeight: '16px', letterSpacing: '0.08em', fontWeight: '600' }],
      },
      borderRadius: {
        sm: '0.125rem',
        DEFAULT: '0.25rem',
        md: '0.375rem',
        lg: '0.5rem',
        xl: '0.75rem',
      },
      spacing: {
        unit: '4px',
        gutter: '16px',
        'panel-gap': '1px',
        'margin-desktop': '32px',
        'margin-mobile': '16px',
      },
    },
  },
  plugins: [],
}
