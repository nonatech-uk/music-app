import { NavLink } from 'react-router-dom'
import AppSwitcher from './AppSwitcher'

const links = [
  { to: '/tracks', label: 'Tracks' },
  { to: '/artists', label: 'Artists' },
  { to: '/review', label: 'Review' },
]

export default function Sidebar() {
  return (
    <aside className="w-48 shrink-0 bg-bg-secondary border-r border-border p-4 flex flex-col gap-1">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-lg font-bold text-text-primary">Music</h1>
        <AppSwitcher />
      </div>
      {links.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          className={({ isActive }) =>
            `block px-3 py-2 rounded text-sm transition-colors ${
              isActive
                ? 'bg-accent text-white'
                : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
            }`
          }
        >
          {label}
        </NavLink>
      ))}
    </aside>
  )
}
