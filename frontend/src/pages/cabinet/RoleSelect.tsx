import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Building2, GraduationCap, Loader2 } from 'lucide-react'
import { api } from '../../api'
import { setProfile, type Role } from '../../profile'

const ROLES: { key: Role; title: string; text: string; Icon: typeof GraduationCap }[] = [
  { key: 'student', title: 'Студент', text: 'История документов, ответы ИИ и решения деканата по вашим заявкам.', Icon: GraduationCap },
  { key: 'dean', title: 'Деканат', text: 'Входящие заявки, краткий анализ ИИ, принять или отклонить с причиной.', Icon: Building2 },
]

export default function RoleSelect() {
  const [role, setRole] = useState<Role>('student')
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: () => api.createProfile({ role, name: name.trim() }),
    onSuccess: (p) => setProfile(p),
  })

  return (
    <div className="max-w-3xl">
      <h1 className="section-title">Кабинет</h1>
      <p className="mt-3 text-ink-600">
        Выберите роль и представьтесь. Вход без пароля — демонстрационный режим: если вы уже входили, введите то же имя, и откроется ваш кабинет.
      </p>
      <form
        className="mt-7 card p-6 sm:p-8"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate()
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          {ROLES.map(({ key, title, text, Icon }) => (
            <button
              key={key}
              type="button"
              aria-pressed={role === key}
              onClick={() => setRole(key)}
              className={`text-left rounded-2xl border-2 p-4 transition ${role === key ? 'border-brand-500 bg-brand-50' : 'border-ink-200 bg-surface hover:border-brand-300'}`}
            >
              <Icon className={role === key ? 'text-brand-600' : 'text-ink-500'} />
              <div className="mt-2 font-semibold text-ink-900">{title}</div>
              <div className="mt-1 text-sm text-ink-600">{text}</div>
            </button>
          ))}
        </div>
        <label className="block mt-5">
          <span className="text-sm font-medium text-ink-900">Как вас зовут</span>
          <input className="input mt-1.5" value={name} onChange={(e) => setName(e.target.value)} placeholder="Иванов Иван" maxLength={120} autoFocus />
        </label>
        {create.error && <div className="mt-3 text-sm text-red-700">{(create.error as Error).message}</div>}
        <button className="btn-primary btn-lg mt-5 w-full sm:w-auto" disabled={!name.trim() || create.isPending}>
          {create.isPending && <Loader2 className="animate-spin" size={18} />} Войти в кабинет
        </button>
      </form>
    </div>
  )
}
