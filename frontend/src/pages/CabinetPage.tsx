import { useProfile } from '../profile'
import RoleSelect from './cabinet/RoleSelect'
import StudentCabinet from './cabinet/StudentCabinet'
import DeanCabinet from './cabinet/DeanCabinet'

export default function CabinetPage() {
  const profile = useProfile()
  if (!profile) return <RoleSelect />
  return profile.role === 'dean' ? <DeanCabinet profile={profile} /> : <StudentCabinet profile={profile} />
}
