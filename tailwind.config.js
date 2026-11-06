/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--color-${name}) / <alpha-value>)`;

export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    // Korvataan oletusasteikko, jotta isot pyöristykset (xl, 2xl) eivät palaa vahingossa
    borderRadius: {
      none: '0',
      sm: 'var(--radius-sm)',
      DEFAULT: 'var(--radius)',
      md: 'var(--radius)',
      lg: 'var(--radius-lg)',
      full: '9999px',
    },
    extend: {
      colors: {
        canvas: token('canvas'),
        backdrop: token('backdrop'),
        surface: token('surface'),
        subtle: token('subtle'),
        raised: token('raised'),
        line: {
          DEFAULT: token('line'),
          strong: token('line-strong'),
        },
        fg: {
          DEFAULT: token('fg'),
          muted: token('fg-muted'),
          subtle: token('fg-subtle'),
        },
        accent: {
          DEFAULT: token('accent'),
          hover: token('accent-hover'),
          fg: token('accent-fg'),
        },
        success: token('success'),
        danger: token('danger'),
        warning: token('warning'),
        score: {
          hot: token('score-hot'),
          good: token('score-good'),
          fair: token('score-fair'),
          low: token('score-low'),
        },
        status: {
          none: token('status-none'),
          broken: token('status-broken'),
          insecure: token('status-insecure'),
          mobile: token('status-mobile'),
          unknown: token('status-unknown'),
          ok: token('status-ok'),
        },
      },
      borderColor: {
        DEFAULT: token('line'),
      },
      // Varjot vain kelluville pinnoille (modaalit, popoverit); muualla ohut reuna
      boxShadow: {
        overlay: 'var(--shadow-overlay)',
        popover: 'var(--shadow-popover)',
        selected: '0 0 0 1px rgb(var(--color-fg))',
        'selected-inset': 'inset 0 0 0 1px rgb(var(--color-fg))',
      },
      spacing: {
        control: 'var(--size-control)',
        'control-sm': 'var(--size-control-sm)',
        'page-x': 'var(--space-page-x)',
        'page-y': 'var(--space-page-y)',
        card: 'var(--space-card)',
        'cell-x': 'var(--space-cell-x)',
        'cell-y': 'var(--space-cell-y)',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', '"SF Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['11px', '16px'],
        xs: ['12px', '16px'],
        sm: ['13px', '20px'],
        base: ['14px', '20px'],
        lg: ['16px', '24px'],
        xl: ['18px', '26px'],
        '2xl': ['24px', '30px'],
      },
    },
  },
  plugins: [],
}
