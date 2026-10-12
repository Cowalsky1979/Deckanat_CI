import { Link, NavLink, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { MessageCircleMore, Moon, Search, ShieldCheck, Sun } from 'lucide-react'
import { getTheme, setTheme, type Theme } from './theme'
import { api } from './api'
import UploadPage from './pages/UploadPage'
import DocumentPage from './pages/DocumentPage'
import RulesPage from './pages/RulesPage'
import AboutPage from './pages/AboutPage'

// верхняя строка шапки с разделами
const topNavCls = ({ isActive }: { isActive: boolean }) =>
  `shrink-0 text-[15px] uppercase tracking-wide transition ${isActive ? 'text-ink-900' : 'text-ink-600 hover:text-ink-900'}`

function TopNavLinks() {
  return (
    <>
      <NavLink to="/" end className={topNavCls}>Студентам</NavLink>
      <NavLink to="/rules" className={topNavCls}>Положение</NavLink>
      <NavLink to="/about" className={topNavCls}>О сервисе</NavLink>
    </>
  )
}

function LogoMark() {
  return (
    <svg viewBox="0 0 40 40" className="h-10 w-10 shrink-0" aria-hidden="true">
      <rect x="3" y="3" width="34" height="34" rx="9" className="fill-brand-500" />
      <path d="M13 10h10l6 6v14a1.5 1.5 0 0 1-1.5 1.5h-14A1.5 1.5 0 0 1 12 30V11.5A1.5 1.5 0 0 1 13 10z" fill="#fff" />
      <path d="M23 10v6h6" fill="#e0efe0" />
      <path d="M15.5 23.5l3 3 6-6.5" fill="none" stroke="#50b848" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Logo() {
  return (
    <NavLink to="/" className="flex items-center gap-2.5 shrink-0" aria-label="Онлайн-деканат — на главную">
      <LogoMark />
      <span className="uppercase font-extrabold text-brand-500 leading-[1.02] tracking-tight">
        <span className="block text-[13px]">Онлайн</span>
        <span className="block text-[19px]">Деканат</span>
      </span>
    </NavLink>
  )
}

function ThemeToggle() {
  const [theme, set] = useState<Theme>(() => getTheme())
  const next: Theme = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={() => {
        setTheme(next)
        set(next)
      }}
      className="inline-flex h-10 w-10 items-center justify-center rounded-full text-ink-500 hover:text-ink-900 hover:bg-panel transition"
      title={theme === 'dark' ? 'Светлая тема' : 'Тёмная тема'}
      aria-label="Переключить тему"
    >
      {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}

// вторая строка шапки: быстрый выбор типа документа
function SubNav() {
  const types = useQuery({ queryKey: ['doc-types'], queryFn: api.docTypes })
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const current = pathname === '/' ? params.get('type') ?? 'auto' : null
  const cls = (active: boolean) =>
    `shrink-0 text-[15px] transition ${active ? 'text-ink-900' : 'text-ink-600 hover:text-ink-900'}`
  return (
    <nav className="tg-hide hidden sm:block border-b border-ink-200">
      <div className="container-x h-[68px] flex items-center gap-8">
        <div className="flex-1 min-w-0 flex items-center gap-8 overflow-x-auto no-scrollbar">
          <Link to="/#upload" className={cls(current === 'auto')}>Автоопределение типа</Link>
          {types.data?.map((t) => (
            <Link key={t.key} to={`/?type=${t.key}#upload`} className={cls(current === t.key)}>
              {t.title}
            </Link>
          ))}
        </div>
        <Link to="/rules?search=1" className="shrink-0 text-ink-700 hover:text-brand-600 transition" title="Поиск по Положению" aria-label="Поиск по Положению">
          <Search size={26} strokeWidth={1.6} />
        </Link>
      </div>
    </nav>
  )
}

// прокрутка к якорю (#upload, #ask) после перехода, пункты Положения крутит сама RulesPage
function ScrollToHash() {
  const { pathname, hash } = useLocation()
  const prevPath = useRef(pathname)
  useEffect(() => {
    const pathChanged = prevPath.current !== pathname
    prevPath.current = pathname
    if (!hash || hash.startsWith('#rule-')) {
      // наверх только при смене страницы, не при смене ?type=
      if (!hash && pathChanged) window.scrollTo({ top: 0 })
      return
    }
    let tries = 0
    const timer = setInterval(() => {
      const el = document.getElementById(hash.slice(1))
      if (el || ++tries > 20) {
        clearInterval(timer)
        el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }, 50)
    return () => clearInterval(timer)
  }, [pathname, hash])
  return null
}

export default function App() {
  const { pathname } = useLocation()
  return (
    <div className="min-h-full flex flex-col">
      <ScrollToHash />
      <header className="sticky top-0 z-20 bg-surface/95 backdrop-blur border-b border-ink-200">
        <div className="container-x h-[70px] flex items-center gap-6 lg:gap-10">
          <Logo />
          <nav className="hidden sm:flex flex-1 min-w-0 items-center gap-6 lg:gap-8 overflow-x-auto no-scrollbar">
            <TopNavLinks />
          </nav>
          <span className="flex-1 sm:hidden" />
          <div className="tg-hide hidden xl:flex items-center gap-2 text-[15px] text-ink-400">
            <ShieldCheck size={18} /> Локально, без внешних API
          </div>
          <ThemeToggle />
          <Link
            to="/#upload"
            className="tg-hide hidden sm:inline-flex h-12 items-center rounded-xl border border-brand-500 px-5 text-[15px] uppercase tracking-wide text-brand-600 hover:bg-brand-50 transition"
          >
            Проверить документ
          </Link>
        </div>
        {/* на телефоне разделы отдельной строкой, иначе не влезают */}
        <nav className="sm:hidden border-t border-ink-200">
          <div className="container-x h-12 flex items-center gap-6 overflow-x-auto no-scrollbar">
            <TopNavLinks />
          </div>
        </nav>
      </header>
      <SubNav />

      <main className="flex-1 container-x py-8 sm:py-10">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/d/:id" element={<DocumentPage />} />
          <Route path="/rules" element={<RulesPage />} />
          <Route path="/about" element={<AboutPage />} />
        </Routes>
      </main>

      {/* плавающая кнопка для вопроса */}
      <Link
        to={pathname.startsWith('/d/') ? '#ask' : '/#ask'}
        className="tg-hide fixed bottom-6 right-6 z-30 hidden sm:inline-flex h-16 w-16 items-center justify-center rounded-full bg-surface text-brand-500 shadow-[0_8px_28px_rgba(35,35,35,0.14)] hover:scale-105 transition"
        title="Задать вопрос по документу"
        aria-label="Задать вопрос по документу"
      >
        <MessageCircleMore size={30} strokeWidth={2} />
      </Link>

      <footer className="tg-hide bg-panel mt-10">
        <div className="container-x py-8 grid gap-4 sm:grid-cols-[1fr_auto] text-sm text-ink-500">
          <div>
            <div className="text-ink-800 font-medium">Предварительная проверка по учебному Положению.</div>
            Окончательное решение принимает сотрудник деканата (п. 1.3). Обработка выполняется локально, без внешних API.
          </div>
          <div className="sm:text-right">
            © 2026 Онлайн-деканат · учебный проект для кейса хакатона Банка «Центр-инвест».
            <br />Не является сервисом банка.
          </div>
        </div>
      </footer>
    </div>
  )
}
