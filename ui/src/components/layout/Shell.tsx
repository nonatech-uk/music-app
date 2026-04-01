import Sidebar from './Sidebar.tsx'

export default function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex w-full min-h-screen bg-bg-primary text-text-primary">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">
        {children}
      </main>
    </div>
  )
}
