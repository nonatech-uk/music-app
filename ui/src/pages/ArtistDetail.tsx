import { useParams, Link } from 'react-router-dom'
import { useArtist } from '../hooks/useArtists.ts'
import LoadingSpinner from '../components/common/LoadingSpinner.tsx'

function formatDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export default function ArtistDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: artist, isLoading } = useArtist(Number(id))

  if (isLoading) return <LoadingSpinner />
  if (!artist) return <p className="text-text-secondary p-8">Artist not found.</p>

  return (
    <div className="space-y-6 max-w-3xl">
      <Link to="/artists" className="text-sm text-text-secondary hover:text-accent">&larr; Back to artists</Link>

      <div className="bg-bg-card border border-border rounded-lg p-6">
        <h2 className="text-xl font-semibold">{artist.name}</h2>
        <div className="flex gap-4 text-sm text-text-secondary mt-2">
          <span><strong className="text-text-primary">{artist.track_count}</strong> tracks</span>
          <span><strong className="text-text-primary">{artist.scrobble_count}</strong> plays</span>
        </div>
      </div>

      {artist.tracks.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-text-secondary mb-2">Tracks</h3>
          <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-bg-secondary">
                  <th className="text-left px-4 py-2 font-medium text-text-secondary">Title</th>
                  <th className="text-left px-4 py-2 font-medium text-text-secondary">Album</th>
                  <th className="text-right px-4 py-2 font-medium text-text-secondary">Plays</th>
                  <th className="text-right px-4 py-2 font-medium text-text-secondary">Last Played</th>
                </tr>
              </thead>
              <tbody>
                {artist.tracks.map(track => (
                  <tr key={track.id} className="border-b border-border last:border-0 hover:bg-bg-hover transition-colors">
                    <td className="px-4 py-2">
                      <Link to={`/tracks/${track.id}`} className="text-accent hover:underline">
                        {track.title}
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-text-secondary">{track.album_title || ''}</td>
                    <td className="px-4 py-2 text-right tabular-nums">{track.scrobble_count}</td>
                    <td className="px-4 py-2 text-right text-text-secondary">{formatDate(track.last_scrobbled)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
