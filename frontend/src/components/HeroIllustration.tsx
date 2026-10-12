// картинка для баннера на главной
// variant: 0 - проверка пройдена, 1 - ответ со ссылкой на пункт, 2 - выравнивание кривого снимка
interface Props {
  variant: number
}

function FieldRow({ y, w, found = true }: { y: number; w: number; found?: boolean }) {
  return (
    <g>
      <rect x="128" y={y} width="62" height="9" rx="4.5" className="fill-ink-200" />
      <rect x="206" y={y - 6} width={w} height="21" rx="6" className={found ? 'fill-brand-50 stroke-brand-500' : 'fill-red-50 stroke-red-500'} strokeWidth="2" />
      <rect x="214" y={y} width={w - 30} height="9" rx="4.5" className={found ? 'fill-brand-300' : 'fill-red-300'} />
    </g>
  )
}

export default function HeroIllustration({ variant }: Props) {
  const tilt = variant === 2 ? -9 : 0
  return (
    <svg viewBox="0 0 520 470" className="w-full max-w-[520px] h-auto overflow-visible" role="img" aria-label="Документ с распознанными полями">
      <defs>
        <filter id="hero-shadow" x="-60%" y="-60%" width="220%" height="240%">
          <feDropShadow dx="0" dy="18" stdDeviation="18" floodColor="#232323" floodOpacity="0.14" />
        </filter>
      </defs>

      {/* задний лист */}
      <g transform="rotate(-8 260 250)">
        <rect x="120" y="70" width="270" height="350" rx="18" className="fill-surface" filter="url(#hero-shadow)" opacity="0.85" />
        <rect x="150" y="110" width="150" height="10" rx="5" className="fill-ink-200" />
        <rect x="150" y="134" width="200" height="8" rx="4" className="fill-ink-100" />
      </g>

      {/* основной лист */}
      <g transform={`rotate(${tilt} 260 250)`} style={{ transition: 'transform .6s ease' }}>
        <rect x="104" y="52" width="300" height="380" rx="20" className="fill-surface" filter="url(#hero-shadow)" />
        <rect x="128" y="82" width="180" height="14" rx="7" className="fill-ink-800" opacity="0.85" />
        <rect x="128" y="106" width="120" height="9" rx="4.5" className="fill-ink-300" />

        <FieldRow y={148} w={150} />
        <FieldRow y={186} w={120} />
        <FieldRow y={224} w={170} />
        <FieldRow y={262} w={110} found={variant !== 0} />
        <FieldRow y={300} w={140} />

        {/* подпись */}
        <path d="M134 382c14-22 22-26 26-14s-6 22 6 10 18-24 24-10 10 6 20-4" fill="none" className="stroke-ink-700" strokeWidth="3" strokeLinecap="round" />
        <rect x="128" y="392" width="100" height="2" className="fill-ink-300" />
        {/* печать */}
        <circle cx="336" cy="372" r="36" fill="none" className="stroke-blue-600" strokeWidth="3" opacity="0.75" />
        <circle cx="336" cy="372" r="25" fill="none" className="stroke-blue-600" strokeWidth="2" opacity="0.55" />
        <path d="M336 357l4.4 9 9.9 1.4-7.2 7 1.7 9.8-8.8-4.6-8.8 4.6 1.7-9.8-7.2-7 9.9-1.4z" className="fill-blue-600" opacity="0.55" />
      </g>

      {variant === 0 && (
        <g>
          <circle cx="420" cy="92" r="44" className="fill-brand-500" filter="url(#hero-shadow)" />
          <path d="M400 93l14 14 26-28" fill="none" stroke="#fff" strokeWidth="8" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      )}

      {variant === 1 && (
        <g filter="url(#hero-shadow)">
          <path d="M300 18h190a16 16 0 0 1 16 16v74a16 16 0 0 1-16 16H352l-26 22v-22h-26a16 16 0 0 1-16-16V34a16 16 0 0 1 16-16z" className="fill-surface" />
          <rect x="304" y="40" width="170" height="10" rx="5" className="fill-ink-300" />
          <rect x="304" y="60" width="130" height="10" rx="5" className="fill-ink-200" />
          <rect x="304" y="82" width="92" height="24" rx="12" className="fill-sun-100 stroke-sun-400" strokeWidth="2" />
          <text x="350" y="99" textAnchor="middle" fontSize="14" fontWeight="700" className="fill-sun-700">п. 3.2</text>
        </g>
      )}

      {variant === 2 && (
        <g className="stroke-brand-500" strokeWidth="6" strokeLinecap="round" fill="none">
          <path d="M70 70v-34h34" />
          <path d="M416 36h34v34" />
          <path d="M450 400v34h-34" />
          <path d="M104 434H70v-34" />
        </g>
      )}
    </svg>
  )
}
