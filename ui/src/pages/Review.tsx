import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useReviewStats,
  useUnresolved,
  useFailed,
  useLowConfidence,
  useDuplicates,
  useUpdateLink,
  useConfirmLink,
  useRejectLink,
  useMergeArtists,
} from '../hooks/useReview.ts'
import type { ReviewItem, DuplicateCandidate } from '../api/types.ts'
import LoadingSpinner from '../components/common/LoadingSpinner.tsx'
import Pagination from '../components/common/Pagination.tsx'

function pct(n: number, d: number) {
  return d ? `${((n / d) * 100).toFixed(1)}%` : '0%'
}

function formatDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const p = max ? (value / max) * 100 : 0
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-text-secondary">
        <span>{label}</span>
        <span>{value.toLocaleString()} / {max.toLocaleString()} ({pct(value, max)})</span>
      </div>
      <div className="h-2 bg-bg-secondary rounded-full overflow-hidden">
        <div className="h-full bg-accent rounded-full transition-all" style={{ width: `${p}%` }} />
      </div>
    </div>
  )
}

function LinkModal({ item, onClose }: { item: ReviewItem; onClose: () => void }) {
  const [artistMbid, setArtistMbid] = useState(item.artist_mbid || '')
  const [recordingMbid, setRecordingMbid] = useState(item.recording_mbid || '')
  const mutation = useUpdateLink()

  const handleSubmit = () => {
    const body: { artist_mbid?: string; recording_mbid?: string } = {}
    if (artistMbid) body.artist_mbid = artistMbid
    if (recordingMbid) body.recording_mbid = recordingMbid
    mutation.mutate({ linkId: item.link_id, body }, { onSuccess: onClose })
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-bg-card border border-border rounded-lg p-6 w-[500px] space-y-4" onClick={e => e.stopPropagation()}>
        <h3 className="font-semibold text-text-primary">Link to MusicBrainz</h3>
        <p className="text-sm text-text-secondary">{item.artist_string} &mdash; {item.track_string}</p>

        <div className="space-y-2">
          <label className="block text-xs text-text-secondary">Artist MBID</label>
          <input
            value={artistMbid}
            onChange={e => setArtistMbid(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            className="w-full px-3 py-1.5 text-sm border border-border rounded-md bg-bg-secondary text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent font-mono"
          />
        </div>

        <div className="space-y-2">
          <label className="block text-xs text-text-secondary">Recording MBID</label>
          <input
            value={recordingMbid}
            onChange={e => setRecordingMbid(e.target.value)}
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            className="w-full px-3 py-1.5 text-sm border border-border rounded-md bg-bg-secondary text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-accent font-mono"
          />
        </div>

        <div className="flex gap-2 justify-end">
          <a
            href={`https://musicbrainz.org/search?query=${encodeURIComponent(`${item.artist_string} ${item.track_string}`)}&type=recording`}
            target="_blank"
            rel="noopener"
            className="px-3 py-1.5 text-sm border border-border rounded-md text-text-secondary hover:text-text-primary"
          >
            Search MB
          </a>
          <button onClick={onClose} className="px-3 py-1.5 text-sm border border-border rounded-md text-text-secondary hover:text-text-primary">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={mutation.isPending || (!artistMbid && !recordingMbid)}
            className="px-3 py-1.5 text-sm bg-accent text-white rounded-md hover:bg-accent/90 disabled:opacity-50"
          >
            {mutation.isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

type Tab = 'unresolved' | 'failed' | 'low-confidence' | 'duplicates'

export default function Review() {
  const [tab, setTab] = useState<Tab>('unresolved')
  const [offset, setOffset] = useState(0)
  const [linkItem, setLinkItem] = useState<ReviewItem | null>(null)
  const limit = 50

  const { data: stats, isLoading: statsLoading } = useReviewStats()

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: 'unresolved', label: 'Unresolved', count: stats ? stats.total_recordings - stats.resolved_recordings - stats.failed_count : undefined },
    { key: 'failed', label: 'Failed', count: stats?.failed_count },
    { key: 'low-confidence', label: 'Low Confidence', count: stats ? stats.confidence_95_99 + stats.confidence_90_95 : undefined },
    { key: 'duplicates', label: 'Duplicates' },
  ]

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Review</h2>

      {/* Stats panel */}
      {statsLoading ? <LoadingSpinner /> : stats && (
        <div className="bg-bg-card border border-border rounded-lg p-4 space-y-3">
          <ProgressBar value={stats.resolved_artists} max={stats.total_artists} label="Artists" />
          <ProgressBar value={stats.resolved_recordings} max={stats.total_recordings} label="Recordings" />
          <ProgressBar value={stats.linked_scrobbles} max={stats.total_scrobbles} label="Scrobbles" />
          <div className="flex gap-4 text-xs text-text-secondary pt-1">
            <span>99%+: {stats.confidence_99_plus.toLocaleString()}</span>
            <span>95-99%: {stats.confidence_95_99}</span>
            <span>90-95%: {stats.confidence_90_95}</span>
            <span>Failed: {stats.failed_count}</span>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-border">
        {tabs.map(t => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setOffset(0) }}
            className={`px-4 py-2 text-sm border-b-2 transition-colors ${
              tab === t.key
                ? 'border-accent text-accent'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}
          >
            {t.label}{t.count !== undefined ? ` (${t.count.toLocaleString()})` : ''}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'unresolved' && <UnresolvedTab limit={limit} offset={offset} setOffset={setOffset} onLink={setLinkItem} />}
      {tab === 'failed' && <FailedTab limit={limit} offset={offset} setOffset={setOffset} onLink={setLinkItem} />}
      {tab === 'low-confidence' && <LowConfidenceTab limit={limit} offset={offset} setOffset={setOffset} onLink={setLinkItem} />}
      {tab === 'duplicates' && <DuplicatesTab />}

      {linkItem && <LinkModal item={linkItem} onClose={() => setLinkItem(null)} />}
    </div>
  )
}

function ReviewTable({
  items,
  showMatch,
  onLink,
}: {
  items: ReviewItem[]
  showMatch?: boolean
  onLink: (item: ReviewItem) => void
}) {
  const confirmMut = useConfirmLink()
  const rejectMut = useRejectLink()

  return (
    <div className="bg-bg-card border border-border rounded-lg overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-bg-secondary">
            <th className="text-left px-4 py-2 font-medium text-text-secondary">Artist</th>
            <th className="text-left px-4 py-2 font-medium text-text-secondary">Track</th>
            {showMatch && <th className="text-left px-4 py-2 font-medium text-text-secondary">Matched</th>}
            {showMatch && <th className="text-right px-4 py-2 font-medium text-text-secondary">Score</th>}
            <th className="text-right px-4 py-2 font-medium text-text-secondary">Plays</th>
            <th className="text-right px-4 py-2 font-medium text-text-secondary">Last Played</th>
            <th className="text-right px-4 py-2 font-medium text-text-secondary">Actions</th>
          </tr>
        </thead>
        <tbody>
          {items.map(item => (
            <tr key={item.link_id} className="border-b border-border last:border-0 hover:bg-bg-hover transition-colors">
              <td className="px-4 py-2 text-text-primary">
                {item.artist_id ? (
                  <Link to={`/artists/${item.artist_id}`} className="text-accent hover:underline">{item.artist_string}</Link>
                ) : item.artist_string}
              </td>
              <td className="px-4 py-2 text-text-secondary">
                {item.track_id ? (
                  <Link to={`/tracks/${item.track_id}`} className="text-accent hover:underline">{item.track_string}</Link>
                ) : item.track_string}
              </td>
              {showMatch && (
                <td className="px-4 py-2 text-text-secondary text-xs">
                  {item.matched_artist && <div>{item.matched_artist}</div>}
                  {item.matched_recording && <div className="text-text-secondary">{item.matched_recording}</div>}
                </td>
              )}
              {showMatch && (
                <td className="px-4 py-2 text-right tabular-nums">
                  {item.resolution_score ? `${(item.resolution_score * 100).toFixed(1)}%` : ''}
                </td>
              )}
              <td className="px-4 py-2 text-right tabular-nums">{item.scrobble_count}</td>
              <td className="px-4 py-2 text-right text-text-secondary">{formatDate(item.last_played)}</td>
              <td className="px-4 py-2 text-right space-x-1">
                <a
                  href={`https://musicbrainz.org/search?query=${encodeURIComponent(`${item.artist_string} ${item.track_string}`)}&type=recording`}
                  target="_blank"
                  rel="noopener"
                  className="inline-block px-2 py-0.5 text-xs border border-border rounded hover:bg-bg-hover"
                >
                  MB
                </a>
                <button
                  onClick={() => onLink(item)}
                  className="px-2 py-0.5 text-xs border border-border rounded hover:bg-bg-hover"
                >
                  Link
                </button>
                {showMatch && item.recording_mbid && (
                  <>
                    <button
                      onClick={() => confirmMut.mutate(item.link_id)}
                      disabled={confirmMut.isPending}
                      className="px-2 py-0.5 text-xs border border-success/50 text-success rounded hover:bg-success/10"
                    >
                      OK
                    </button>
                    <button
                      onClick={() => rejectMut.mutate(item.link_id)}
                      disabled={rejectMut.isPending}
                      className="px-2 py-0.5 text-xs border border-danger/50 text-danger rounded hover:bg-danger/10"
                    >
                      Reject
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function UnresolvedTab({ limit, offset, setOffset, onLink }: { limit: number; offset: number; setOffset: (n: number) => void; onLink: (item: ReviewItem) => void }) {
  const { data, isLoading } = useUnresolved({ limit, offset })
  if (isLoading) return <LoadingSpinner />
  if (!data?.items.length) return <p className="text-text-secondary py-8">All recordings resolved.</p>
  return (
    <>
      <ReviewTable items={data.items} onLink={onLink} />
      <Pagination offset={offset} limit={limit} total={data.total} hasMore={data.has_more} onChange={setOffset} />
    </>
  )
}

function FailedTab({ limit, offset, setOffset, onLink }: { limit: number; offset: number; setOffset: (n: number) => void; onLink: (item: ReviewItem) => void }) {
  const { data, isLoading } = useFailed({ limit, offset })
  if (isLoading) return <LoadingSpinner />
  if (!data?.items.length) return <p className="text-text-secondary py-8">No failed matches.</p>
  return (
    <>
      <ReviewTable items={data.items} onLink={onLink} />
      <Pagination offset={offset} limit={limit} total={data.total} hasMore={data.has_more} onChange={setOffset} />
    </>
  )
}

function LowConfidenceTab({ limit, offset, setOffset, onLink }: { limit: number; offset: number; setOffset: (n: number) => void; onLink: (item: ReviewItem) => void }) {
  const { data, isLoading } = useLowConfidence({ limit, offset })
  if (isLoading) return <LoadingSpinner />
  if (!data?.items.length) return <p className="text-text-secondary py-8">No low-confidence matches to review.</p>
  return (
    <>
      <ReviewTable items={data.items} showMatch onLink={onLink} />
      <Pagination offset={offset} limit={limit} total={data.total} hasMore={data.has_more} onChange={setOffset} />
    </>
  )
}

function DuplicatesTab() {
  const { data, isLoading } = useDuplicates({ type: 'artist', threshold: 0.7 })
  const mergeMut = useMergeArtists()

  if (isLoading) return <LoadingSpinner />
  if (!data?.items.length) return <p className="text-text-secondary py-8">No duplicate candidates found.</p>

  return (
    <div className="bg-bg-card border border-border rounded-lg overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-bg-secondary">
            <th className="text-left px-4 py-2 font-medium text-text-secondary">Artist A</th>
            <th className="text-right px-4 py-2 font-medium text-text-secondary">Tracks</th>
            <th className="text-left px-4 py-2 font-medium text-text-secondary">Artist B</th>
            <th className="text-right px-4 py-2 font-medium text-text-secondary">Tracks</th>
            <th className="text-right px-4 py-2 font-medium text-text-secondary">Similarity</th>
            <th className="text-right px-4 py-2 font-medium text-text-secondary">Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((d: DuplicateCandidate, i: number) => (
            <tr key={i} className="border-b border-border last:border-0 hover:bg-bg-hover transition-colors">
              <td className="px-4 py-2 text-text-primary">
                <Link to={`/artists/${d.id_a}`} className="text-accent hover:underline">{d.name_a}</Link>
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{d.count_a}</td>
              <td className="px-4 py-2 text-text-primary">
                <Link to={`/artists/${d.id_b}`} className="text-accent hover:underline">{d.name_b}</Link>
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{d.count_b}</td>
              <td className="px-4 py-2 text-right tabular-nums">{(d.similarity * 100).toFixed(0)}%</td>
              <td className="px-4 py-2 text-right space-x-1">
                <button
                  onClick={() => mergeMut.mutate({ keepId: d.id_a, removeId: d.id_b })}
                  disabled={mergeMut.isPending}
                  className="px-2 py-0.5 text-xs border border-border rounded hover:bg-bg-hover"
                  title={`Keep "${d.name_a}"`}
                >
                  Keep A
                </button>
                <button
                  onClick={() => mergeMut.mutate({ keepId: d.id_b, removeId: d.id_a })}
                  disabled={mergeMut.isPending}
                  className="px-2 py-0.5 text-xs border border-border rounded hover:bg-bg-hover"
                  title={`Keep "${d.name_b}"`}
                >
                  Keep B
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
