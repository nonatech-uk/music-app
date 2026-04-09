import { Link, NavLink } from 'react-router-dom'
import { AppSwitcher } from '@mees/shared-ui'

const links = [
  { to: '/tracks', label: 'Tracks' },
  { to: '/artists', label: 'Artists' },
  { to: '/review', label: 'Review' },
]

interface SidebarProps {
  className?: string
  onNavigate?: () => void
}

export default function Sidebar({ className, onNavigate }: SidebarProps) {
  return (
    <aside className={`w-48 shrink-0 bg-bg-secondary border-r border-border p-4 flex flex-col gap-1 ${className ?? ''}`}>
      <div className="flex items-center justify-between mb-4">
        <Link to="/" className="text-lg font-bold text-text-primary hover:text-accent transition-colors">Music</Link>
        <AppSwitcher currentApp="Music" />
      </div>
      {links.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
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
