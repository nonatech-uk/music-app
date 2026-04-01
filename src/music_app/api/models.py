"""Pydantic request/response models."""

from __future__ import annotations

from pydantic import BaseModel


class ArtistItem(BaseModel):
    id: int
    name: str
    track_count: int = 0
    scrobble_count: int = 0


class ArtistList(BaseModel):
    items: list[ArtistItem]
    total: int
    has_more: bool


class ArtistDetail(ArtistItem):
    tracks: list[TrackItem] = []


class TrackItem(BaseModel):
    id: int
    title: str
    album_title: str | None = None
    length_secs: int | None = None
    artists: list[str] = []
    scrobble_count: int = 0
    last_scrobbled: str | None = None


class TrackList(BaseModel):
    items: list[TrackItem]
    total: int
    has_more: bool


class TrackDetail(TrackItem):
    # Enrichment data
    artist_genres: list[str] | None = None
    spotify_track_id: str | None = None
    tempo: float | None = None
    energy: float | None = None
    valence: float | None = None
    danceability: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    album_title_canonical: str | None = None
    first_release_year: int | None = None


class TrackUpdate(BaseModel):
    title: str | None = None
    album_title: str | None = None
    length_secs: int | None = None
    artists: list[str] | None = None


class ScrobbleItem(BaseModel):
    id: int
    listened_at: str
    track_id: int
    track_title: str
    artist_names: list[str]
    album_title: str | None = None
    duration: int | None = None


class ScrobbleList(BaseModel):
    items: list[ScrobbleItem]
    total: int
    has_more: bool


# --- Review models ---

class ReviewStats(BaseModel):
    total_artists: int
    resolved_artists: int
    total_recordings: int
    resolved_recordings: int
    total_scrobbles: int
    linked_scrobbles: int
    failed_count: int
    confidence_99_plus: int
    confidence_95_99: int
    confidence_90_95: int


class ReviewItem(BaseModel):
    link_id: int
    artist_id: int | None = None
    track_id: int | None = None
    artist_string: str
    track_string: str
    scrobble_count: int
    last_played: str | None = None
    resolution_method: str | None = None
    resolution_score: float | None = None
    matched_artist: str | None = None
    matched_recording: str | None = None
    artist_mbid: str | None = None
    recording_mbid: str | None = None
    reviewed_at: str | None = None


class ReviewList(BaseModel):
    items: list[ReviewItem]
    total: int
    has_more: bool


class LinkUpdate(BaseModel):
    artist_mbid: str | None = None
    recording_mbid: str | None = None


class DuplicateCandidate(BaseModel):
    id_a: int
    name_a: str
    count_a: int
    id_b: int
    name_b: str
    count_b: int
    similarity: float


class DuplicateList(BaseModel):
    items: list[DuplicateCandidate]


class MergeRequest(BaseModel):
    keep_id: int
    remove_id: int


# Rebuild forward refs for ArtistDetail which references TrackItem
ArtistDetail.model_rebuild()
