/**
 * Generates the PWA icon set and the favicon from the design tokens.
 *
 * Run with `npm run icons`. The output is committed, because a build should not depend on
 * a raster step, but it is generated rather than drawn so the mark cannot drift from the
 * accent token — change `--color-accent` and re-run, and the icons follow.
 *
 * The mark is the "K" tile from `plan/design-system.md`: accent-filled rounded square,
 * white glyph. No image library: a small RGBA rasteriser with 4× supersampling, then a
 * hand-rolled PNG writer (zlib is in Node). That is cheaper than adding a native
 * dependency for four files.
 */

import { deflateSync } from 'node:zlib'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { brandColors } from './tokenColors.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const PUBLIC_DIR = resolve(here, '..', 'public')
const ICON_DIR = resolve(PUBLIC_DIR, 'icons')

const SUPERSAMPLE = 4

function hexToRgb(hex) {
  const value = hex.replace('#', '')
  const full = value.length === 3 ? [...value].map((c) => c + c).join('') : value
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ]
}

/** Signed-distance-ish test: is (x, y) inside a rounded rectangle? */
function insideRoundedRect(x, y, left, top, right, bottom, radius) {
  if (x < left || x > right || y < top || y > bottom) return false
  const cx = Math.min(Math.max(x, left + radius), right - radius)
  const cy = Math.min(Math.max(y, top + radius), bottom - radius)
  const dx = x - cx
  const dy = y - cy
  return dx * dx + dy * dy <= radius * radius
}

function insidePolygon(x, y, points) {
  let inside = false
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i]
    const [xj, yj] = points[j]
    const intersects = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi
    if (intersects) inside = !inside
  }
  return inside
}

/** A thick line segment as a quad, so the K's arms are one primitive each. */
function segmentQuad([x1, y1], [x2, y2], thickness) {
  const dx = x2 - x1
  const dy = y2 - y1
  const length = Math.hypot(dx, dy)
  const nx = (-dy / length) * (thickness / 2)
  const ny = (dx / length) * (thickness / 2)
  return [
    [x1 + nx, y1 + ny],
    [x2 + nx, y2 + ny],
    [x2 - nx, y2 - ny],
    [x1 - nx, y1 - ny],
  ]
}

/**
 * The K glyph, as a stem plus two arms, in a unit box scaled by `scale` about the centre.
 * Returns the shapes in icon pixel coordinates.
 */
function glyphShapes(size, scale) {
  const box = size * scale
  const originX = (size - box) / 2
  const originY = (size - box) / 2
  const px = (u) => originX + u * box
  const py = (v) => originY + v * box

  const stemW = 0.2 * box
  const left = px(0.12)
  const top = py(0.06)
  const bottom = py(0.94)
  const right = px(0.9)
  const junctionY = py(0.52)
  const junctionX = left + stemW

  return [
    // stem
    [
      [left, top],
      [junctionX, top],
      [junctionX, bottom],
      [left, bottom],
    ],
    segmentQuad([junctionX - stemW * 0.3, junctionY], [right, top], stemW),
    segmentQuad([junctionX - stemW * 0.3, junctionY], [right, bottom], stemW),
  ]
}

/**
 * @param {number} size          icon edge in px
 * @param {boolean} maskable     true → full-bleed background, glyph inside the 80% safe zone
 */
function renderIcon(size, maskable, colors) {
  const [br, bg, bb] = hexToRgb(colors.accent)
  const [fr, fg, fb] = hexToRgb(colors.onAccent)

  const ss = size * SUPERSAMPLE
  // The app icon is a rounded square; a maskable icon is cropped by the platform, so it
  // fills the canvas and keeps the glyph small enough to survive a circular mask.
  const radius = maskable ? 0 : ss * 0.22
  const glyphScale = maskable ? 0.5 : 0.62
  const shapes = glyphShapes(ss, glyphScale)

  const pixels = Buffer.alloc(size * size * 4)

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let bgHits = 0
      let fgHits = 0
      for (let sy = 0; sy < SUPERSAMPLE; sy++) {
        for (let sx = 0; sx < SUPERSAMPLE; sx++) {
          const px = x * SUPERSAMPLE + sx + 0.5
          const py = y * SUPERSAMPLE + sy + 0.5
          if (!insideRoundedRect(px, py, 0, 0, ss, ss, radius)) continue
          bgHits++
          if (shapes.some((shape) => insidePolygon(px, py, shape))) fgHits++
        }
      }
      const samples = SUPERSAMPLE * SUPERSAMPLE
      const coverage = bgHits / samples
      const glyph = fgHits / samples
      // Composite glyph over the tile, then the tile over transparency.
      const r = Math.round((br * (coverage - glyph) + fr * glyph) / (coverage || 1))
      const g = Math.round((bg * (coverage - glyph) + fg * glyph) / (coverage || 1))
      const b = Math.round((bb * (coverage - glyph) + fb * glyph) / (coverage || 1))
      const offset = (y * size + x) * 4
      pixels[offset] = coverage ? r : 0
      pixels[offset + 1] = coverage ? g : 0
      pixels[offset + 2] = coverage ? b : 0
      pixels[offset + 3] = Math.round(coverage * 255)
    }
  }

  return pixels
}

// --- minimal PNG writer ----------------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Int32Array(256)
  for (let n = 0; n < 256; n++) {
    let c = n
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    table[n] = c
  }
  return table
})()

function crc32(buffer) {
  let c = 0xffffffff
  for (const byte of buffer) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8)
  return (c ^ 0xffffffff) >>> 0
}

function chunk(type, data) {
  const length = Buffer.alloc(4)
  length.writeUInt32BE(data.length)
  const typeAndData = Buffer.concat([Buffer.from(type, 'ascii'), data])
  const crc = Buffer.alloc(4)
  crc.writeUInt32BE(crc32(typeAndData))
  return Buffer.concat([length, typeAndData, crc])
}

function encodePng(size, pixels) {
  const ihdr = Buffer.alloc(13)
  ihdr.writeUInt32BE(size, 0)
  ihdr.writeUInt32BE(size, 4)
  ihdr[8] = 8 // bit depth
  ihdr[9] = 6 // colour type: RGBA
  // 10..12: compression, filter, interlace — all zero (deflate, adaptive, none)

  // One filter byte per scanline; filter 0 (None) keeps the writer honest and small.
  const raw = Buffer.alloc(size * (size * 4 + 1))
  for (let y = 0; y < size; y++) {
    const rowStart = y * (size * 4 + 1)
    raw[rowStart] = 0
    pixels.copy(raw, rowStart + 1, y * size * 4, (y + 1) * size * 4)
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ])
}

// --- output ------------------------------------------------------------------------------

const colors = brandColors()
mkdirSync(ICON_DIR, { recursive: true })

const targets = [
  { file: 'icon-192.png', size: 192, maskable: false },
  { file: 'icon-512.png', size: 512, maskable: false },
  { file: 'icon-512-maskable.png', size: 512, maskable: true },
  { file: 'apple-touch-icon-180.png', size: 180, maskable: true },
]

for (const target of targets) {
  const pixels = renderIcon(target.size, target.maskable, colors)
  writeFileSync(resolve(ICON_DIR, target.file), encodePng(target.size, pixels))
  console.log(`icons: wrote ${target.file} (${target.size}px)`)
}

// The favicon stays vector — it is the same mark, and an SVG favicon is sharp at any size.
const faviconGlyph = glyphShapes(64, 0.62)
  .map((shape) => `<polygon points="${shape.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' ')}" />`)
  .join('')
writeFileSync(
  resolve(PUBLIC_DIR, 'favicon.svg'),
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">\n` +
    `  <!-- Generated by scripts/generate-icons.mjs from --color-accent. Do not edit. -->\n` +
    `  <rect width="64" height="64" rx="14" fill="${colors.accent}"/>\n` +
    `  <g fill="${colors.onAccent}">${faviconGlyph}</g>\n` +
    `</svg>\n`,
)
console.log('icons: wrote favicon.svg')
