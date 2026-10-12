// Профиль кабинета: входа нет, роль и имя хранятся в браузере.
import { useSyncExternalStore } from 'react'

export type Role = 'student' | 'dean'

export interface Profile {
  id: string
  role: Role
  name: string
  telegram_user_id: string | null
}

export const ROLE_TITLES: Record<Role, string> = { student: 'Студент', dean: 'Деканат' }

const KEY = 'dekanat-profile'
let cached: Profile | null | undefined
const listeners = new Set<() => void>()

function read(): Profile | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Profile) : null
  } catch {
    return null
  }
}

export function getProfile(): Profile | null {
  if (cached === undefined) cached = read()
  return cached
}

export function setProfile(p: Profile | null) {
  cached = p
  try {
    if (p) localStorage.setItem(KEY, JSON.stringify(p))
    else localStorage.removeItem(KEY)
  } catch {
    /* приватный режим */
  }
  listeners.forEach((l) => l())
}

export const clearProfile = () => setProfile(null)

function subscribe(l: () => void) {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

export function useProfile(): Profile | null {
  return useSyncExternalStore(subscribe, getProfile, getProfile)
}
