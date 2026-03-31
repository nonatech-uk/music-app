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
