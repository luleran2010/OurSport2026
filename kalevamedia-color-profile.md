# Kaleva Media — Frontend Color Profile

Source: https://www.kalevamedia.fi/ (WordPress, Enfold theme + `kaleva-campaigns` child theme)
Extracted: 2026-10-24, from the live stylesheets (`dynamic_avia/kaleva_campaigns.css`, `kaleva-campaigns/style.css`, `post-14.css`) and the computed styles of the rendered homepage.

## Character

The palette is quiet and editorial: mostly white and black, with warm sand/khaki neutrals as the brand accent and one deep blue for calls to action. The page sits in a boxed layout on a sand-colored canvas (`#C5BCA5`). Headers and the footer use pale beige tones, and secondary text and nav links use a muted bronze-brown (`#8B784A`).

## Core palette

| Token | Hex | Swatch | Role on the site |
|---|---|---|---|
| `--km-black` | `#000000` | ![](https://placehold.co/24x24/000000/000000.png) | Body text, H3–H6, primary/secondary accents (Enfold `main-color-*`) |
| `--km-ink` | `#18191A` | ![](https://placehold.co/24x24/18191A/18191A.png) | H1 & H2 headings |
| `--km-white` | `#FFFFFF` | ![](https://placehold.co/24x24/FFFFFF/FFFFFF.png) | Main content and header background |
| `--km-sand` | `#C5BCA5` | ![](https://placehold.co/24x24/C5BCA5/C5BCA5.png) | **Brand neutral**: page canvas (`html`), socket/bottom bar, borders |
| `--km-sand-light` | `#D1C6AE` | ![](https://placehold.co/24x24/D1C6AE/D1C6AE.png) | Top meta/social bar |
| `--km-sand-dark` | `#B4AB94` | ![](https://placehold.co/24x24/B4AB94/B4AB94.png) | Icon backgrounds, hover state of sand |
| `--km-bronze` | `#8B784A` | ![](https://placehold.co/24x24/8B784A/8B784A.png) | Main navigation links, footer text & meta |
| `--km-bronze-deep` | `#645635` | ![](https://placehold.co/24x24/645635/645635.png) | Darker bronze (hover/pressed) |
| `--km-cream` | `#F6F4EF` | ![](https://placehold.co/24x24/F6F4EF/F6F4EF.png) | Footer background |
| `--km-beige` | `#EFEBE2` | ![](https://placehold.co/24x24/EFEBE2/EFEBE2.png) | Secondary surface (`bg2`): cards, inputs, alternating rows |
| `--km-beige-header` | `#F0ECE4` | ![](https://placehold.co/24x24/F0ECE4/F0ECE4.png) | Header `bg2`, active menu highlight |
| `--km-blue` | `#244F83` | ![](https://placehold.co/24x24/244F83/244F83.png) | **Primary CTA**: buttons (filled + 2px border), default text links |

## Supporting & semantic colors

| Token | Hex | Swatch | Role |
|---|---|---|---|
| `--km-link` | `#0062A9` | ![](https://placehold.co/24x24/0062A9/0062A9.png) | In-content links and `strong` inside articles (child theme override) |
| `--km-gray-text` | `#696A62` | ![](https://placehold.co/24x24/696A62/696A62.png) | Captions, blockquotes, "tumma harmaa" paragraph style |
| `--km-gray-mid` | `#767676` | ![](https://placehold.co/24x24/767676/767676.png) | Secondary buttons, muted UI |
| `--km-gray-line` | `#D9D9D9` | ![](https://placehold.co/24x24/D9D9D9/D9D9D9.png) | Header border |
| `--km-gray-light` | `#DFDED9` | ![](https://placehold.co/24x24/DFDED9/DFDED9.png) | Light borders |
| `--km-charcoal` | `#2D2D2D` | ![](https://placehold.co/24x24/2D2D2D/2D2D2D.png) | Dark bars and buttons |
| `--km-orange` | `#EA8C1C` | ![](https://placehold.co/24x24/EA8C1C/EA8C1C.png) | Slider meta / separator text accents |
| `--km-error` | `#B21125` | ![](https://placehold.co/24x24/B21125/B21125.png) | Form validation errors (text + 2px top/bottom rule) |
| `--km-success` | `#65A500` | ![](https://placehold.co/24x24/65A500/65A500.png) | Ad disclaimer badge |
| `--km-sky` | `#C6E6F4` | ![](https://placehold.co/24x24/C6E6F4/C6E6F4.png) | Socket `bg2` (used rarely) |

## Surface map (how the page is layered)

```
html canvas ............ #C5BCA5  sand
├─ top meta bar ........ #D1C6AE  text #000000
├─ header .............. #FFFFFF  nav links #8B784A, border #D9D9D9, active #F0ECE4
├─ main content ........ #FFFFFF  text #000000, H1/H2 #18191A, links #0062A9
│   └─ CTA button ...... #244F83  text #FFFFFF
├─ footer .............. #F6F4EF  text #8B784A, headings #000000, borders #C5BCA5
└─ socket (bottom bar) . #C5BCA5  text #000000
```

## Contrast check (WCAG 2.x)

| Foreground / Background | Ratio | AA normal | AA large |
|---|---|---|---|
| `#000000` / `#FFFFFF` | 21.00 | ✅ | ✅ |
| `#18191A` / `#FFFFFF` | 17.61 | ✅ | ✅ |
| `#FFFFFF` / `#244F83` (CTA) | 8.33 | ✅ | ✅ |
| `#B21125` / `#FFFFFF` | 7.00 | ✅ | ✅ |
| `#0062A9` / `#FFFFFF` | 6.33 | ✅ | ✅ |
| `#696A62` / `#FFFFFF` | 5.47 | ✅ | ✅ |
| `#FFFFFF` / `#767676` | 4.54 | ✅ | ✅ |
| `#8B784A` / `#FFFFFF` (nav) | 4.30 | ❌ | ✅ |
| `#8B784A` / `#F6F4EF` (footer) | 3.91 | ❌ | ✅ |
| `#000000` / `#C5BCA5` | 11.11 | ✅ | ✅ |
| `#000000` / `#EFEBE2` | 17.65 | ✅ | ✅ |
| `#EA8C1C` / `#FFFFFF` | 2.54 | ❌ | ❌ |
| `#FFFFFF` / `#C5BCA5` | 1.89 | ❌ | ❌ |

Notes for reuse:
- Bronze `#8B784A` passes only for large or bold text. For small body text, darken it to `#645635`.
- Orange `#EA8C1C` is decorative only. Don't use it for text on white.
- Never put white text on sand. Use black or `#18191A`.

## Typography (for context)

- Primary family: **Open Sans** (400 / 500 / 600 / 700). Headings use Open Sans or *Open Sans Condensed* (`.h1-cond-musta`).
- Also loaded: **DIN Pro**, **Axiforma** and **Tinos** (serif, editorial accents).
- Sizes: H1 36px, H2 20px, H3 18px.

## CSS variables

```css
:root {
  /* Neutrals */
  --km-black: #000000;
  --km-ink: #18191A;
  --km-white: #FFFFFF;
  --km-charcoal: #2D2D2D;
  --km-gray-text: #696A62;
  --km-gray-mid: #767676;
  --km-gray-line: #D9D9D9;
  --km-gray-light: #DFDED9;

  /* Brand warm neutrals */
  --km-sand: #C5BCA5;
  --km-sand-light: #D1C6AE;
  --km-sand-dark: #B4AB94;
  --km-bronze: #8B784A;
  --km-bronze-deep: #645635;
  --km-cream: #F6F4EF;
  --km-beige: #EFEBE2;
  --km-beige-header: #F0ECE4;

  /* Accents */
  --km-blue: #244F83;
  --km-link: #0062A9;
  --km-orange: #EA8C1C;
  --km-sky: #C6E6F4;

  /* Semantic */
  --km-error: #B21125;
  --km-success: #65A500;

  /* Roles */
  --color-bg: var(--km-white);
  --color-canvas: var(--km-sand);
  --color-surface: var(--km-beige);
  --color-footer-bg: var(--km-cream);
  --color-text: var(--km-black);
  --color-heading: var(--km-ink);
  --color-text-muted: var(--km-gray-text);
  --color-nav: var(--km-bronze);
  --color-border: var(--km-sand);
  --color-link: var(--km-link);
  --color-primary: var(--km-blue);
  --color-on-primary: var(--km-white);
}
```

## Tailwind config snippet

```js
// tailwind.config.js → theme.extend.colors
kaleva: {
  black: '#000000',
  ink: '#18191A',
  sand: { DEFAULT: '#C5BCA5', light: '#D1C6AE', dark: '#B4AB94' },
  bronze: { DEFAULT: '#8B784A', deep: '#645635' },
  cream: '#F6F4EF',
  beige: { DEFAULT: '#EFEBE2', header: '#F0ECE4' },
  blue: '#244F83',
  link: '#0062A9',
  orange: '#EA8C1C',
  gray: { text: '#696A62', mid: '#767676', line: '#D9D9D9', light: '#DFDED9', charcoal: '#2D2D2D' },
  error: '#B21125',
  success: '#65A500',
},
```

---
*Excluded: WordPress block-editor preset colors and gradients (`--wp--preset--*`), which are core defaults and not part of the site's design, and the cookie-consent (Gravito CMP) overlay.*
