import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTracks } from '../hooks/useTracks.ts'
import LoadingSpinner from '../components/common/LoadingSpinner.tsx'
import Pagination from '../components/common/Pagination.tsx'

function formatDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function Tracks() {
  const [q, setQ] = useState('')
  const [sort, setSort] = useState('recent')
  const [offset, setOffset] = useState(0)
  const limit = 50

  const { data, isLoading } = useTracks({
    q: q || undefined,
    sort,
    limit,
    offset,
  })

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Tracks</h2>

      <div className="flex gap-3 flex-wrap items-center">
        <input
          type="text"
          placeholder="Search tracks or artists..."
          value={q}
          onChange={e => { setQ(e.target.value); setOffset(0) }}
          className="px-3 py-1.5 text-sm border border-border rounded-md bg-bg-secondary text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent w-full sm:w-72"
        />
        <select
          value={sort}
          onChange={e => { setSort(e.target.value); setOffset(0) }}
          className="px-3 py-1.5 text-sm border border-border rounded-md bg-bg-secondary text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
        >
          <option value="recent">Recently played</option>
          <option value="title">Title A-Z</option>
          <option value="scrobbles">Most played</option>
        </select>
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : !data?.items.length ? (
        <p className="text-text-secondary py-8">No tracks found.</p>
      ) : (
        <>
          <div className="bg-bg-card border border-border rounded-lg overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-bg-secondary">
                  <th className="text-left px-4 py-2 font-medium text-text-secondary">Title</th>
                  <th className="text-left px-4 py-2 font-medium text-text-secondary">Artist</th>
                  <th className="text-left px-4 py-2 font-medium text-text-secondary">Album</th>
                  <th className="text-right px-4 py-2 font-medium text-text-secondary">Plays</th>
                  <th className="text-right px-4 py-2 font-medium text-text-secondary">Last Played</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map(track => (
                  <tr key={track.id} className="border-b border-border last:border-0 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2">
                      <Link to={`/tracks/${track.id}`} className="text-accent hover:underline">
                        {track.title}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-text-secondary">{track.artists.join(', ')}</td>
                    <td className="px-4 py-2 text-text-secondary">{track.album_title || ''}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{track.scrobble_count}</td>
                    <td className="px-4 py-2 text-right text-text-secondary">{formatDate(track.last_scrobbled)}</td>
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
