import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useArtists } from '../hooks/useArtists.ts'
import LoadingSpinner from '../components/common/LoadingSpinner.tsx'
import Pagination from '../components/common/Pagination.tsx'

export default function Artists() {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('scrobbles')
  const [offset, setOffset] = useState(0)
  const limit = 50

  const { data, isLoading } = useArtists({
    q: q || undefined,
    sort,
    limit,
    offset,
  })

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Artists</h2>

      <div className="flex gap-3 flex-wrap items-center">
        <input
          type="text"
          placeholder="Search artists..."
          value={q}
          onChange={e => { setQ(e.target.value); setOffset(0) }}
          className="px-3 py-1.5 text-sm border border-border rounded-md bg-bg-secondary text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent w-72"
        />
        <select
          value={sort}
          onChange={e => { setSort(e.target.value); setOffset(0) }}
          className="px-3 py-1.5 text-sm border border-border rounded-md bg-bg-secondary text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
        >
          <option value="scrobbles">Most played</option>
          <option value="name">Name A-Z</option>
        </select>
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : !data?.items.length ? (
        <p className="text-text-secondary py-8">No artists found.</p>
      ) : (
        <>
          <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-bg-secondary">
                  <th className="text-left px-4 py-2 font-medium text-text-secondary">Name</th>
                  <th className="text-right px-4 py-2 font-medium text-text-secondary">Tracks</th>
                  <th className="text-right px-4 py-2 font-medium text-text-secondary">Plays</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(artist => (
                  <tr key={artist.id} className="border-b border-border last:border-0 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2">
                      <Link to={`/artists/${artist.id}`} className="text-accent hover:underline">
                        {artist.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums">{artist.track_count}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{artist.scrobble_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <Pagination
            offset={offset}
            limit={limit}
            total={data.total}
            hasMore={data.has_more}
            onChange={setOffset}
          />
        </>
      )}
    </div>
  )
}
