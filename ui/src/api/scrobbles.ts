import { apiFetch } from './client.ts'
import type { ScrobbleList } from './types.ts'

export function fetchScrobbles(limit = 50, offset = 0) {
  return apiFetch<ScrobbleList>(`/scrobbles?limit=${limit}&offset=${offset}`)
}
