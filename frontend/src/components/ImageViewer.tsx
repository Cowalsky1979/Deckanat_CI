import { TransformComponent, TransformWrapper } from 'react-zoom-pan-pinch'
import type { FieldValue } from '../api'

interface Props {
  src: string
  size: [number, number]
  fields: FieldValue[]
  transform: number[][] | null // матрица исходный -> нормализованный, по ней bbox переводим обратно на исходник
  highlight: string | null
  onSelect: (key: string | null) => void
  isPdfOriginal?: boolean
}

function invert3(m: number[][]): number[][] | null {
  const [[a, b, c], [d, e, f], [g, h, i]] = m
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g
  const det = a * A + b * B + c * C
  if (Math.abs(det) < 1e-12) return null
  const D = -(b * i - c * h), E = a * i - c * g, F = -(a * h - b * g)
  const G = b * f - c * e, H = -(a * f - c * d), I = a * e - b * d
  return [[A / det, D / det, G / det], [B / det, E / det, H / det], [C / det, F / det, I / det]]
}

function project(bbox: [number, number, number, number], inv: number[][] | null): string {
  const [x1, y1, x2, y2] = bbox
  const pts: [number, number][] = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
  if (!inv) return pts.map((p) => p.join(',')).join(' ')
  return pts
    .map(([x, y]) => {
      const w = inv[2][0] * x + inv[2][1] * y + inv[2][2]
      return [(inv[0][0] * x + inv[0][1] * y + inv[0][2]) / w, (inv[1][0] * x + inv[1][1] * y + inv[1][2]) / w].join(',')
    })
    .join(' ')
}

const color = (f: FieldValue) => (f.kind === 'mark' ? (f.found ? '#2563eb' : '#dc2626') : f.found ? '#50b848' : '#dc2626')

export default function ImageViewer({ src, size, fields, transform, highlight, onSelect, isPdfOriginal }: Props) {
  const [w, h] = size
  const inv = transform ? invert3(transform) : null
  if (isPdfOriginal) {
    return (
      <div className="rounded-xl overflow-hidden bg-ink-100 border border-ink-200">
        <object data={src} type="application/pdf" className="w-full h-[70vh]">
          <div className="p-4 text-sm">PDF: <a className="underline" href={src} target="_blank" rel="noreferrer">открыть исходный файл</a></div>
        </object>
      </div>
    )
  }
  return (
    <div className="rounded-xl overflow-hidden bg-ink-100 border border-ink-200">
      <TransformWrapper minScale={0.5} maxScale={6} wheel={{ step: 0.15 }} doubleClick={{ mode: 'reset' }}>
        <TransformComponent wrapperClass="!w-full !h-[70vh]" contentClass="!w-full">
          <div className="relative w-full" style={{ aspectRatio: `${w} / ${h}` }}>
            <img src={src} alt="документ" className="doc-image absolute inset-0 w-full h-full object-contain select-none" draggable={false} />
            <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
              {fields
                .filter((f) => f.bbox)
                .map((f) => {
                  const pad = Math.max(4, (f.bbox![3] - f.bbox![1]) * 0.25)
                  const bb: [number, number, number, number] = [f.bbox![0] - pad, f.bbox![1] - pad, f.bbox![2] + pad, f.bbox![3] + pad]
                  const active = highlight === f.key
                  return (
                    <g key={f.key} onClick={() => onSelect(active ? null : f.key)} className="cursor-pointer">
                      <polygon
                        points={project(bb, inv)}
                        fill={active ? color(f) : 'transparent'}
                        fillOpacity={active ? 0.18 : 0}
                        stroke={color(f)}
                        strokeWidth={active ? Math.max(4, w / 250) : Math.max(2, w / 500)}
                        strokeOpacity={active ? 1 : highlight ? 0.35 : 0.8}
                        className={active ? 'box-highlight' : ''}
                      >
                        <title>{f.label}: {String(f.value)}</title>
                      </polygon>
                    </g>
                  )
                })}
            </svg>
          </div>
        </TransformComponent>
      </TransformWrapper>
    </div>
  )
}
