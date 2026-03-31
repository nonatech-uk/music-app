-- Music scrobble database schema
-- Database: scrobble

CREATE TABLE artist (
    id          serial PRIMARY KEY,
    name        text NOT NULL UNIQUE,
    name_lower  text NOT NULL UNIQUE
);

CREATE TABLE track (
    id          serial PRIMARY KEY,
    title       text NOT NULL,
    title_lower text NOT NULL,
    album_title text,
    length_secs integer,
    UNIQUE (title_lower, album_title)
);

CREATE TABLE track_artist (
    track_id    integer NOT NULL REFERENCES track(id),
    artist_id   integer NOT NULL REFERENCES artist(id),
    PRIMARY KEY (track_id, artist_id)
);

CREATE INDEX idx_track_artist_artist_id ON track_artist (artist_id);

CREATE TABLE scrobble (
    id          serial PRIMARY KEY,
    listened_at timestamptz NOT NULL,
    track_id    integer NOT NULL REFERENCES track(id),
    duration    integer,
    origin      text,
    UNIQUE (listened_at, track_id)
);

CREATE INDEX idx_scrobble_listened_at ON scrobble (listened_at);
CREATE INDEX idx_scrobble_track_id ON scrobble (track_id);


-- ============================================================
-- Music metadata enrichment tables
-- ============================================================

-- Canonical artist from MusicBrainz
CREATE TABLE IF NOT EXISTS music_artist (
    mbid            uuid PRIMARY KEY,
    name            text NOT NULL,
    sort_name       text,
    country         text,
    begin_year      smallint,
    end_year        smallint,
    spotify_id      text,
    genres          text[],
    tags            text[],
    bio             text,
    spotify_popularity smallint,
    needs_refresh   boolean NOT NULL DEFAULT true,
    mb_raw          jsonb,
    spotify_raw     jsonb,
    lastfm_raw      jsonb,
    enriched_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Album / EP / Single (MusicBrainz release group)
CREATE TABLE IF NOT EXISTS music_release_group (
    mbid            uuid PRIMARY KEY,
    artist_mbid     uuid NOT NULL REFERENCES music_artist(mbid),
    title           text NOT NULL,
    type            text,
    first_release_date text,
    first_release_year smallint,
    spotify_album_id text,
    mb_raw          jsonb,
    spotify_raw     jsonb,
    enriched_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_music_rg_artist ON music_release_group (artist_mbid);

-- Individual track / recording
CREATE TABLE IF NOT EXISTS music_recording (
    mbid            uuid PRIMARY KEY,
    artist_mbid     uuid NOT NULL REFERENCES music_artist(mbid),
    release_group_mbid uuid REFERENCES music_release_group(mbid),
    title           text NOT NULL,
    duration_ms     integer,
    isrc            text,
    spotify_track_id text,
    -- Spotify audio features
    tempo           real,
    energy          real,
    valence         real,
    danceability    real,
    acousticness    real,
    instrumentalness real,
    loudness_db     real,
    key             smallint,
    mode            smallint,
    time_signature  smallint,
    spotify_popularity smallint,
    mb_raw          jsonb,
    spotify_raw     jsonb,
    needs_refresh   boolean NOT NULL DEFAULT true,
    enriched_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_music_rec_artist ON music_recording (artist_mbid);
CREATE INDEX IF NOT EXISTS idx_music_rec_rg ON music_recording (release_group_mbid);

-- Maps raw scrobble strings to canonical MBIDs
CREATE TABLE IF NOT EXISTS music_scrobble_link (
    id              serial PRIMARY KEY,
    artist_string   text NOT NULL,
    track_string    text NOT NULL,
    artist_id       integer REFERENCES artist(id),
    track_id        integer REFERENCES track(id),
    artist_mbid     uuid REFERENCES music_artist(mbid),
    recording_mbid  uuid REFERENCES music_recording(mbid),
    resolution_method text,
    resolution_score real,
    resolved_at     timestamptz,
    UNIQUE (artist_string, track_string)
);

CREATE INDEX IF NOT EXISTS idx_scrobble_link_artist_mbid ON music_scrobble_link (artist_mbid);
CREATE INDEX IF NOT EXISTS idx_scrobble_link_recording_mbid ON music_scrobble_link (recording_mbid);

-- Enriched view joining scrobbles to metadata
CREATE OR REPLACE VIEW music_scrobble_enriched AS
SELECT
    s.id            AS scrobble_id,
    s.listened_at,
    a.name          AS artist_name,
    t.title         AS track_title,
    t.album_title,
    sl.resolution_method,
    sl.resolution_score,
    ma.mbid         AS artist_mbid,
    ma.genres       AS artist_genres,
    ma.tags         AS artist_tags,
    mr.mbid         AS recording_mbid,
    mr.spotify_track_id,
    mr.tempo,
    mr.energy,
    mr.valence,
    mr.danceability,
    rg.mbid         AS release_group_mbid,
    rg.title        AS album_title_canonical,
    rg.type         AS release_type,
    rg.first_release_year
FROM scrobble s
JOIN track t ON t.id = s.track_id
JOIN track_artist ta ON ta.track_id = t.id
JOIN artist a ON a.id = ta.artist_id
LEFT JOIN music_scrobble_link sl
    ON sl.artist_string = a.name_lower
   AND sl.track_string  = t.title_lower
LEFT JOIN music_artist ma ON ma.mbid = sl.artist_mbid
LEFT JOIN music_recording mr ON mr.mbid = sl.recording_mbid
LEFT JOIN music_release_group rg ON rg.mbid = mr.release_group_mbid;
