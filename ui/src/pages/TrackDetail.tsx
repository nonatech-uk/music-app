import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useTrack, useTrackScrobbles, useUpdateTrack, useDeleteTrack } from '../hooks/useTracks.ts'
import LoadingSpinner from '../components/common/LoadingSpinner.tsx'

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function StatBadge({ label, value }: { label: string; value: string | number | null }) {
  if (value === null || value === undefined) return null
  const display = typeof value === 'number' ? value.toFixed(2) : value
  return (
    <div className="bg-bg-secondary border border-border rounded px-3 py-2">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="text-sm font-medium">{display}</div>
    </div>
  )
}

export default function TrackDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const trackId = Number(id)
  const { data: track, isLoading } = useTrack(trackId)
  const { data: scrobbles } = useTrackScrobbles(trackId, 20)
  const updateMutation = useUpdateTrack()
  const deleteMutation = useDeleteTrack()

  const [editing, setEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editAlbum, setEditAlbum] = useState('')
  const [editArtists, setEditArtists] = useState('')

  if (isLoading) return <LoadingSpinner />
  if (!track) return <p className="text-text-secondary p-8">Track not found.</p>

  function startEdit() {
    if (!track) return
    setEditTitle(track.title)
    setEditAlbum(track.album_title || '')
    setEditArtists(track.artists.join(', '))
    setEditing(true)
  }

  function saveEdit() {
    updateMutation.mutate(
      {
        id: trackId,
        data: {
          title: editTitle,
          album_title: editAlbum || undefined,
          artists: editArtists.split(',').map(s => s.trim()).filter(Boolean),
        },
      },
      { onSuccess: () => setEditing(false) },
    )
  }

  function handleDelete() {
    if (!confirm('Delete this track and all its scrobbles?')) return
    deleteMutation.mutate(trackId, {
      onSuccess: () => navigate('/tracks'),
    })
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <Link to="/tracks" className="text-sm text-text-secondary hover:text-accent">&larr; Back to tracks</Link>

      <div className="bg-bg-card border border-border rounded-lg p-6 space-y-4">
        {editing ? (
          <div className="space-y-3">
            <div>
              <label className="text-xs text-text-secondary">Title</label>
              <input value={editTitle} onChange={e => setEditTitle(e.target.value)}
                className="w-full mt-1 px-3 py-1.5 text-sm border border-border rounded bg-bg-secondary text-text-primary focus:outline-none focus:ring-1 focus:ring-accent" />
            </div>
            <div>
              <label className="text-xs text-text-secondary">Album</label>
              <input value={editAlbum} onChange={e => setEditAlbum(e.target.value)}
                className="w-full mt-1 px-3 py-1.5 text-sm border border-border rounded bg-bg-secondary text-text-primary focus:outline-none focus:ring-1 focus:ring-accent" />
            </div>
            <div>
              <label className="text-xs text-text-secondary">Artists (comma-separated)</label>
              <input value={editArtists} onChange={e => setEditArtists(e.target.value)}
                className="w-full mt-1 px-3 py-1.5 text-sm border border-border rounded bg-bg-secondary text-text-primary focus:outline-none focus:ring-1 focus:ring-accent" />
            </div>
            <div className="flex gap-2">
              <button onClick={saveEdit} disabled={updateMutation.isPending}
                className="px-4 py-1.5 text-sm rounded bg-accent text-white hover:bg-accent-hover disabled:opacity-50">
                {updateMutation.isPending ? 'Saving...' : 'Save'}
              </button>
              <button onClick={() => setEditing(false)}
                className="px-4 py-1.5 text-sm rounded border border-border hover:bg-bg-hover">
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-xl font-semibold">{track.title}</h2>
                <p className="text-text-secondary">{track.artists.join(', ')}</p>
                {track.album_title && <p className="text-sm text-text-secondary mt-1">{track.album_title}</p>}
              </div>
              <div className="flex gap-2">
                <button onClick={startEdit}
                  className="px-3 py-1.5 text-sm rounded border border-border hover:bg-bg-hover">
                  Edit
                </button>
                <button onClick={handleDelete} disabled={deleteMutation.isPending}
                  className="px-3 py-1.5 text-sm rounded border border-danger text-danger hover:bg-danger hover:text-white disabled:opacity-50">
                  Delete
                </button>
              </div>
            </div>

            <div className="flex gap-4 text-sm">
              <span><strong>{track.scrobble_count}</strong> plays</span>
              {track.length_secs && <span>{Math.floor(track.length_secs / 60)}:{String(track.length_secs % 60).padStart(2, '0')}</span>}
              {track.album_title_canonical && <span>Album: {track.album_title_canonical}</span>}
              {track.first_release_year && <span>Year: {track.first_release_year}</span>}
            </div>
          </>
        )}
      </div>

      {/* Enrichment data */}
      {(track.tempo || track.energy || track.valence || track.danceability) && (
        <div>
          <h3 className="text-sm font-medium text-text-secondary mb-2">Audio Features</h3>
          <div className="flex flex-wrap gap-2">
            <StatBadge label="Tempo" value={track.tempo ? Math.round(track.tempo) + ' BPM' : null} />
            <StatBadge label="Energy" value={track.energy} />
            <StatBadge label="Valence" value={track.valence} />
            <StatBadge label="Danceability" value={track.danceability} />
            <StatBadge label="Acousticness" value={track.acousticness} />
            <StatBadge label="Instrumentalness" value={track.instrumentalness} />
          </div>
        </div>
      )}

      {track.artist_genres && track.artist_genres.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-text-secondary mb-2">Genres</h3>
          <div className="flex flex-wrap gap-1">
            {track.artist_genres.map(g => (
              <span key={g} className="px-2 py-0.5 text-xs rounded-full bg-bg-secondary border border-border">{g}</span>
            ))}
          </div>
        </div>
      )}

      {/* Recent scrobbles */}
      {scrobbles && scrobbles.items.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-text-secondary mb-2">Recent Plays</h3>
          <div className="bg-bg-card border border-border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                {scrobbles.items.map(s => (
                  <tr key={s.id} className="border-b border-border last:border-0 hover:bg-bg-hover">
                    <td className="px-4 py-2 text-text-secondary">{formatDateTime(s.listened_at)}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-text-secondary">
                      {s.duration ? `${Math.floor(s.duration / 60)}:${String(s.duration % 60).padStart(2, '0')}` : ''}
                    </td>
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
