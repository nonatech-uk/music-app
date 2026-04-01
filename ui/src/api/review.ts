import { apiFetch } from './client.ts'
import type { ReviewStats, ReviewList, DuplicateList } from './types.ts'

export function fetchReviewStats(): Promise<ReviewStats> {
  return apiFetch('/review/stats')
}

export function fetchUnresolved(params: { limit: number; offset: number }): Promise<ReviewList> {
  const sp = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  return apiFetch(`/review/unresolved?${sp}`)
}

export function fetchFailed(params: { limit: number; offset: number }): Promise<ReviewList> {
  const sp = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  return apiFetch(`/review/failed?${sp}`)
}

export function fetchLowConfidence(params: { threshold?: number; limit: number; offset: number }): Promise<ReviewList> {
  const sp = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
  if (params.threshold !== undefined) sp.set('threshold', String(params.threshold))
  return apiFetch(`/review/low-confidence?${sp}`)
}

export function fetchDuplicates(params: { type: string; threshold?: number }): Promise<DuplicateList> {
  const sp = new URLSearchParams({ type: params.type })
  if (params.threshold !== undefined) sp.set('threshold', String(params.threshold))
  return apiFetch(`/review/duplicates?${sp}`)
}

export function updateLink(linkId: number, body: { artist_mbid?: string; recording_mbid?: string }): Promise<{ status: string }> {
  return apiFetch(`/review/link/${linkId}`, { method: 'PUT', body: JSON.stringify(body) })
}

export function confirmLink(linkId: number): Promise<{ status: string }> {
  return apiFetch(`/review/confirm/${linkId}`, { method: 'POST' })
}

export function rejectLink(linkId: number): Promise<{ status: string }> {
  return apiFetch(`/review/reject/${linkId}`, { method: 'POST' })
}

export function mergeArtists(keepId: number, removeId: number): Promise<{ status: string }> {
  return apiFetch('/review/merge', { method: 'POST', body: JSON.stringify({ keep_id: keepId, remove_id: removeId }) })
}
