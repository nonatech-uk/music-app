import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchTracks, fetchTrack, updateTrack, deleteTrack, fetchTrackScrobbles } from '../api/tracks.ts'
import type { TrackFilters } from '../api/tracks.ts'
import type { TrackUpdate } from '../api/types.ts'

export function useTracks(filters: TrackFilters) {
  return useQuery({ queryKey: ['tracks', filters], queryFn: () => fetchTracks(filters) })
}

export function useTrack(id: number) {
  return useQuery({ queryKey: ['track', id], queryFn: () => fetchTrack(id) })
}

export function useTrackScrobbles(id: number, limit = 50, offset = 0) {
  return useQuery({
    queryKey: ['track-scrobbles', id, limit, offset],
    queryFn: () => fetchTrackScrobbles(id, limit, offset),
  })
}

export function useUpdateTrack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: TrackUpdate }) => updateTrack(id, data),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: ['track', v.id] })
      void qc.invalidateQueries({ queryKey: ['tracks'] })
    },
  })
}

export function useDeleteTrack() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteTrack(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tracks'] })
    },
  })
}
