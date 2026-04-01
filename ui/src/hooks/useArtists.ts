import { useQuery } from '@tanstack/react-query'
import { fetchArtists, fetchArtist } from '../api/artists.ts'
import type { ArtistFilters } from '../api/artists.ts'

export function useArtists(filters: ArtistFilters) {
  return useQuery({ queryKey: ['artists', filters], queryFn: () => fetchArtists(filters) })
}

export function useArtist(id: number) {
  return useQuery({ queryKey: ['artist', id], queryFn: () => fetchArtist(id) })
}
