import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchReviewStats,
  fetchUnresolved,
  fetchFailed,
  fetchLowConfidence,
  fetchDuplicates,
  updateLink,
  confirmLink,
  rejectLink,
  mergeArtists,
} from '../api/review.ts'

export function useReviewStats() {
  return useQuery({ queryKey: ['review-stats'], queryFn: fetchReviewStats })
}

export function useUnresolved(params: { limit: number; offset: number }) {
  return useQuery({ queryKey: ['review-unresolved', params], queryFn: () => fetchUnresolved(params) })
}

export function useFailed(params: { limit: number; offset: number }) {
  return useQuery({ queryKey: ['review-failed', params], queryFn: () => fetchFailed(params) })
}

export function useLowConfidence(params: { threshold?: number; limit: number; offset: number }) {
  return useQuery({ queryKey: ['review-low-confidence', params], queryFn: () => fetchLowConfidence(params) })
}

export function useDuplicates(params: { type: string; threshold?: number }) {
  return useQuery({ queryKey: ['review-duplicates', params], queryFn: () => fetchDuplicates(params) })
}

export function useUpdateLink() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ linkId, body }: { linkId: number; body: { artist_mbid?: string; recording_mbid?: string } }) =>
      updateLink(linkId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-stats'] })
      qc.invalidateQueries({ queryKey: ['review-unresolved'] })
      qc.invalidateQueries({ queryKey: ['review-failed'] })
      qc.invalidateQueries({ queryKey: ['review-low-confidence'] })
    },
  })
}

export function useConfirmLink() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (linkId: number) => confirmLink(linkId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-stats'] })
      qc.invalidateQueries({ queryKey: ['review-low-confidence'] })
    },
  })
}

export function useRejectLink() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (linkId: number) => rejectLink(linkId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-stats'] })
      qc.invalidateQueries({ queryKey: ['review-low-confidence'] })
      qc.invalidateQueries({ queryKey: ['review-unresolved'] })
    },
  })
}

export function useMergeArtists() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ keepId, removeId }: { keepId: number; removeId: number }) => mergeArtists(keepId, removeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-duplicates'] })
      qc.invalidateQueries({ queryKey: ['review-stats'] })
    },
  })
}
