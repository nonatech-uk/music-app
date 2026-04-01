import { apiFetch } from './client.ts'
import type { TrackList, TrackDetail, TrackUpdate, ScrobbleList } from './types.ts'

export interface TrackFilters {
  q?: string
  sort?: string
  limit?: number
  offset?: number
}

export function fetchTracks(filters: TrackFilters = {}) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  })
  return apiFetch<TrackList>(`/tracks${params.toString() ? '?' + params : ''}`)
}

export function fetchTrack(id: number) {
  return apiFetch<TrackDetail>(`/tracks/${id}`)
}

export function updateTrack(id: number, data: TrackUpdate) {
  return apiFetch<TrackDetail>(`/tracks/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export function deleteTrack(id: number) {
  return apiFetch<{ status: string }>(`/tracks/${id}`, { method: 'DELETE' })
}

export function fetchTrackScrobbles(id: number, limit = 50, offset = 0) {
  return apiFetch<ScrobbleList>(`/tracks/${id}/scrobbles?limit=${limit}&offset=${offset}`)
}
