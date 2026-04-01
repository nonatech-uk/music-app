import { apiFetch } from './client.ts'
import type { ArtistList, ArtistDetail } from './types.ts'

export interface ArtistFilters {
  q?: string
  sort?: string
  limit?: number
  offset?: number
}

export function fetchArtists(filters: ArtistFilters = {}) {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  })
  return apiFetch<ArtistList>(`/artists${params.toString() ? '?' + params : ''}`)
}

export function fetchArtist(id: number) {
  return apiFetch<ArtistDetail>(`/artists/${id}`)
}
