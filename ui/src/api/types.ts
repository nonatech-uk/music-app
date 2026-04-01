export interface TrackItem {
  id: number
  title: string
  album_title: string | null
  length_secs: number | null
  artists: string[]
  scrobble_count: number
  last_scrobbled: string | null
}

export interface TrackList {
  items: TrackItem[]
  total: number
  has_more: boolean
}

export interface TrackDetail extends TrackItem {
  artist_genres: string[] | null
  spotify_track_id: string | null
  tempo: number | null
  energy: number | null
  valence: number | null
  danceability: number | null
  acousticness: number | null
  instrumentalness: number | null
  album_title_canonical: string | null
  first_release_year: number | null
}

export interface TrackUpdate {
  title?: string
  album_title?: string
  length_secs?: number
  artists?: string[]
}

export interface ArtistItem {
  id: number
  name: string
  track_count: number
  scrobble_count: number
}

export interface ArtistList {
  items: ArtistItem[]
  total: number
  has_more: boolean
}

export interface ArtistDetail extends ArtistItem {
  tracks: TrackItem[]
}

export interface ScrobbleItem {
  id: number
  listened_at: string
  track_id: number
  track_title: string
  artist_names: string[]
  album_title: string | null
  duration: number | null
}

export interface ScrobbleList {
  items: ScrobbleItem[]
  total: number
  has_more: boolean
}

// Review types

export interface ReviewStats {
  total_artists: number
  resolved_artists: number
  total_recordings: number
  resolved_recordings: number
  total_scrobbles: number
  linked_scrobbles: number
  failed_count: number
  confidence_99_plus: number
  confidence_95_99: number
  confidence_90_95: number
}

export interface ReviewItem {
  link_id: number
  artist_id: number | null
  track_id: number | null
  artist_string: string
  track_string: string
  scrobble_count: number
  last_played: string | null
  resolution_method: string | null
  resolution_score: number | null
  matched_artist: string | null
  matched_recording: string | null
  artist_mbid: string | null
  recording_mbid: string | null
  reviewed_at: string | null
}

export interface ReviewList {
  items: ReviewItem[]
  total: number
  has_more: boolean
}

export interface DuplicateCandidate {
  id_a: number
  name_a: string
  count_a: number
  id_b: number
  name_b: string
  count_b: number
  similarity: number
}

export interface DuplicateList {
  items: DuplicateCandidate[]
}
