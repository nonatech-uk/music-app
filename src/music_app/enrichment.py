"""Music metadata enrichment pipeline.

Resolves scrobbled artist/track strings into canonical MusicBrainz identifiers,
then enriches with Spotify audio features and Last.fm tags/bios.

Run as: python -m music_app.enrichment
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen

import asyncpg
import musicbrainzngs
from rapidfuzz import fuzz
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

MB_ARTIST_CAP = int(os.environ.get("MB_ARTIST_CAP", "200"))
MB_RECORDING_CAP = int(os.environ.get("MB_RECORDING_CAP", "500"))
SPOTIFY_CAP = int(os.environ.get("SPOTIFY_CAP", "500"))
LASTFM_CAP = int(os.environ.get("LASTFM_CAP", "1000"))
FUZZY_THRESHOLD = int(os.environ.get("FUZZY_THRESHOLD", "90"))
HC_UUID = os.environ.get("HC_UUID", "")
HC_BASE = os.environ.get("HC_BASE", "https://hc.mees.st/ping")

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")

musicbrainzngs.set_useragent("PIF-Enricher", "1.0", "stu@mees.st")


# ---------------------------------------------------------------------------
# Schema bootstrap (idempotent)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS music_recording (
    mbid            uuid PRIMARY KEY,
    artist_mbid     uuid NOT NULL REFERENCES music_artist(mbid),
    release_group_mbid uuid REFERENCES music_release_group(mbid),
    title           text NOT NULL,
    duration_ms     integer,
    isrc            text,
    spotify_track_id text,
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
"""


# ---------------------------------------------------------------------------
# Healthcheck helpers
# ---------------------------------------------------------------------------

def hc_ping(suffix: str = "") -> None:
    if not HC_UUID:
        return
    url = f"{HC_BASE}/{HC_UUID}{suffix}"
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", "PIF-Enricher/1.0")
        urlopen(req, timeout=10)
    except Exception as e:
        print(f"  Healthcheck ping failed ({url}): {e}")


# ---------------------------------------------------------------------------
# MusicBrainz helpers
# ---------------------------------------------------------------------------

MB_RATE_INTERVAL = 1.1  # seconds between MB API calls


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(musicbrainzngs.WebServiceError),
)
def mb_search_artists(name: str, limit: int = 5):
    time.sleep(MB_RATE_INTERVAL)
    return musicbrainzngs.search_artists(artist=name, limit=limit)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    retry=retry_if_exception_type(musicbrainzngs.WebServiceError),
)
def mb_search_recordings(title: str, artist: str, limit: int = 5):
    time.sleep(MB_RATE_INTERVAL)
    return musicbrainzngs.search_recordings(
        recording=title, artist=artist, limit=limit
    )


def _parse_year(life_span: dict, key: str) -> int | None:
    val = life_span.get(key, "")
    if val and len(val) >= 4:
        try:
            return int(val[:4])
        except ValueError:
            pass
    return None


def _parse_release_year(date_str: str | None) -> int | None:
    if date_str and len(date_str) >= 4:
        try:
            return int(date_str[:4])
        except ValueError:
            pass
    return None


async def _upsert_artist(pg: asyncpg.Connection, mb_artist: dict) -> str | None:
    """Insert or update a music_artist row from a MusicBrainz artist result."""
    mbid = mb_artist.get("id")
    if not mbid:
        return None

    name = mb_artist.get("name", "")
    sort_name = mb_artist.get("sort-name", "")
    country = mb_artist.get("country")
    life_span = mb_artist.get("life-span", {})
    begin_year = _parse_year(life_span, "begin")
    end_year = _parse_year(life_span, "end")

    await pg.execute(
        """INSERT INTO music_artist (mbid, name, sort_name, country, begin_year, end_year, mb_raw)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           ON CONFLICT (mbid) DO UPDATE SET
               name = EXCLUDED.name,
               sort_name = EXCLUDED.sort_name,
               country = EXCLUDED.country,
               begin_year = EXCLUDED.begin_year,
               end_year = EXCLUDED.end_year,
               mb_raw = EXCLUDED.mb_raw""",
        mbid, name, sort_name, country, begin_year, end_year,
        json.dumps(mb_artist),
    )
    return mbid


async def _upsert_release_group(
    pg: asyncpg.Connection, rg: dict, artist_mbid: str
) -> str | None:
    """Insert or update a music_release_group from a MusicBrainz release."""
    mbid = rg.get("id")
    if not mbid:
        return None

    title = rg.get("title", "")
    rg_type = rg.get("primary-type") or rg.get("type")
    first_release_date = rg.get("first-release-date", "")
    first_release_year = _parse_release_year(first_release_date)

    await pg.execute(
        """INSERT INTO music_release_group (mbid, artist_mbid, title, type, first_release_date, first_release_year, mb_raw)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           ON CONFLICT (mbid) DO UPDATE SET
               title = EXCLUDED.title,
               type = EXCLUDED.type,
               first_release_date = EXCLUDED.first_release_date,
               first_release_year = EXCLUDED.first_release_year,
               mb_raw = EXCLUDED.mb_raw""",
        mbid, artist_mbid, title, rg_type, first_release_date or None,
        first_release_year, json.dumps(rg),
    )
    return mbid


# ---------------------------------------------------------------------------
# Pass 1: MusicBrainz resolution
# ---------------------------------------------------------------------------

async def pass1_musicbrainz(pg: asyncpg.Connection) -> dict:
    """Resolve raw artist/track strings to MusicBrainz IDs."""
    stats = {"artists_resolved": 0, "artists_failed": 0, "recordings_resolved": 0, "recordings_failed": 0}

    # Step 1a: Seed unresolved link rows from existing artist/track pairs
    await pg.execute("""
        INSERT INTO music_scrobble_link (artist_string, track_string, artist_id, track_id)
        SELECT DISTINCT a.name_lower, t.title_lower, a.id, t.id
        FROM track_artist ta
        JOIN artist a ON a.id = ta.artist_id
        JOIN track t ON t.id = ta.track_id
        ON CONFLICT (artist_string, track_string) DO NOTHING
    """)

    # Step 1b: Resolve artists
    unresolved_artists = await pg.fetch("""
        SELECT DISTINCT sl.artist_string, sl.artist_id, a.name
        FROM music_scrobble_link sl
        JOIN artist a ON a.id = sl.artist_id
        WHERE sl.artist_mbid IS NULL
          AND sl.resolution_method IS DISTINCT FROM 'failed'
        ORDER BY sl.artist_string
        LIMIT $1
    """, MB_ARTIST_CAP)

    print(f"Pass 1a: Resolving {len(unresolved_artists)} artists against MusicBrainz...")

    for row in unresolved_artists:
        artist_name = row["name"]
        artist_string = row["artist_string"]

        try:
            result = mb_search_artists(artist_name)
            artists = result.get("artist-list", [])

            best_match = None
            best_score = 0.0
            for candidate in artists:
                score = fuzz.ratio(
                    artist_name.lower(), candidate.get("name", "").lower()
                ) / 100.0
                if score > best_score:
                    best_score = score
                    best_match = candidate

            if best_match and best_score >= FUZZY_THRESHOLD / 100.0:
                mbid = await _upsert_artist(pg, best_match)
                if mbid:
                    await pg.execute("""
                        UPDATE music_scrobble_link
                        SET artist_mbid = $1, resolution_score = $2,
                            resolution_method = 'mb_search', resolved_at = now()
                        WHERE artist_string = $3 AND artist_mbid IS NULL
                    """, mbid, best_score, artist_string)
                    stats["artists_resolved"] += 1
                    print(f"  Artist: {artist_name} -> {best_match['name']} ({best_score:.0%})")
                    continue

            # Below threshold or no match
            await pg.execute("""
                UPDATE music_scrobble_link
                SET resolution_method = 'failed', resolution_score = $1, resolved_at = now()
                WHERE artist_string = $2 AND artist_mbid IS NULL
            """, best_score if best_match else 0.0, artist_string)
            stats["artists_failed"] += 1
            print(f"  Artist: {artist_name} -> no match ({best_score:.0%})")

        except Exception as e:
            print(f"  Artist: {artist_name} -> error: {e}")
            stats["artists_failed"] += 1

    # Step 1c: Resolve recordings for artists that have MBIDs
    unresolved_recordings = await pg.fetch("""
        SELECT sl.track_string, sl.artist_string, sl.artist_mbid,
               t.title, a.name AS artist_name, sl.track_id,
               (SELECT COUNT(*) FROM scrobble s WHERE s.track_id = sl.track_id) AS play_count
        FROM music_scrobble_link sl
        JOIN track t ON t.id = sl.track_id
        JOIN artist a ON a.id = sl.artist_id
        WHERE sl.artist_mbid IS NOT NULL
          AND sl.recording_mbid IS NULL
          AND sl.resolution_method != 'failed'
        ORDER BY play_count DESC
        LIMIT $1
    """, MB_RECORDING_CAP)

    print(f"\nPass 1b: Resolving {len(unresolved_recordings)} recordings against MusicBrainz...")

    for row in unresolved_recordings:
        track_title = row["title"]
        artist_name = row["artist_name"]
        artist_mbid = row["artist_mbid"]
        track_string = row["track_string"]
        artist_string = row["artist_string"]

        try:
            result = mb_search_recordings(track_title, artist_name)
            recordings = result.get("recording-list", [])

            best_match = None
            best_score = 0.0
            for candidate in recordings:
                title_score = fuzz.ratio(
                    track_title.lower(), candidate.get("title", "").lower()
                ) / 100.0
                # Also check artist credit matches
                artist_credits = candidate.get("artist-credit", [])
                artist_score = 0.0
                for credit in artist_credits:
                    if isinstance(credit, dict) and "artist" in credit:
                        s = fuzz.ratio(
                            artist_name.lower(),
                            credit["artist"].get("name", "").lower()
                        ) / 100.0
                        artist_score = max(artist_score, s)

                combined = (title_score * 0.7) + (artist_score * 0.3)
                if combined > best_score:
                    best_score = combined
                    best_match = candidate

            if best_match and best_score >= FUZZY_THRESHOLD / 100.0:
                rec_mbid = best_match.get("id")
                title = best_match.get("title", track_title)
                duration_ms = best_match.get("length")
                if duration_ms:
                    duration_ms = int(duration_ms)

                # Extract ISRC if available
                isrc = None
                isrc_list = best_match.get("isrc-list", [])
                if isrc_list:
                    isrc = isrc_list[0]

                # Extract release group from first release
                rg_mbid = None
                releases = best_match.get("release-list", [])
                if releases:
                    release = releases[0]
                    rg = release.get("release-group", {})
                    if rg.get("id"):
                        rg_mbid = await _upsert_release_group(pg, rg, str(artist_mbid))

                # Insert recording
                await pg.execute("""
                    INSERT INTO music_recording (mbid, artist_mbid, release_group_mbid, title, duration_ms, isrc, mb_raw)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (mbid) DO UPDATE SET
                        title = EXCLUDED.title,
                        duration_ms = COALESCE(EXCLUDED.duration_ms, music_recording.duration_ms),
                        isrc = COALESCE(EXCLUDED.isrc, music_recording.isrc),
                        release_group_mbid = COALESCE(EXCLUDED.release_group_mbid, music_recording.release_group_mbid),
                        mb_raw = EXCLUDED.mb_raw
                """, rec_mbid, artist_mbid, rg_mbid, title, duration_ms, isrc,
                    json.dumps(best_match))

                # Update link
                await pg.execute("""
                    UPDATE music_scrobble_link
                    SET recording_mbid = $1, resolution_score = $2,
                        resolution_method = 'mb_search', resolved_at = now()
                    WHERE artist_string = $3 AND track_string = $4
                """, rec_mbid, best_score, artist_string, track_string)
                stats["recordings_resolved"] += 1
                print(f"  Recording: {artist_name} - {track_title} -> {title} ({best_score:.0%})")
                continue

            stats["recordings_failed"] += 1
            print(f"  Recording: {artist_name} - {track_title} -> no match ({best_score:.0%})")

        except Exception as e:
            print(f"  Recording: {artist_name} - {track_title} -> error: {e}")
            stats["recordings_failed"] += 1

    return stats


# ---------------------------------------------------------------------------
# Pass 2: Spotify enrichment
# ---------------------------------------------------------------------------

async def pass2_spotify(pg: asyncpg.Connection) -> dict:
    """Enrich recordings with Spotify track IDs and audio features."""
    stats = {"tracks_matched": 0, "tracks_failed": 0, "features_fetched": 0}

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("Pass 2: Skipping Spotify enrichment (no credentials)")
        return stats

    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials

    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    ))

    # Step 2a: Find Spotify track IDs for recordings that don't have them
    recordings = await pg.fetch("""
        SELECT mr.mbid, mr.title, ma.name AS artist_name, ma.mbid AS artist_mbid, ma.spotify_id
        FROM music_recording mr
        JOIN music_artist ma ON ma.mbid = mr.artist_mbid
        WHERE mr.spotify_track_id IS NULL
        LIMIT $1
    """, SPOTIFY_CAP)

    print(f"\nPass 2a: Searching Spotify for {len(recordings)} recordings...")

    track_ids_to_fetch: list[tuple[str, str]] = []  # (recording_mbid, spotify_track_id)

    for rec in recordings:
        try:
            query = f"track:{rec['title']} artist:{rec['artist_name']}"
            result = sp.search(q=query, type="track", limit=1)
            items = result.get("tracks", {}).get("items", [])

            if items:
                track = items[0]
                spotify_track_id = track["id"]
                spotify_popularity = track.get("popularity")

                # Also grab spotify album ID for release group
                album = track.get("album", {})
                spotify_album_id = album.get("id")

                await pg.execute("""
                    UPDATE music_recording
                    SET spotify_track_id = $1, spotify_popularity = $2
                    WHERE mbid = $3
                """, spotify_track_id, spotify_popularity, rec["mbid"])

                # Update release group spotify_album_id if we have one
                if spotify_album_id:
                    await pg.execute("""
                        UPDATE music_release_group
                        SET spotify_album_id = $1
                        WHERE mbid = (SELECT release_group_mbid FROM music_recording WHERE mbid = $2)
                          AND spotify_album_id IS NULL
                    """, spotify_album_id, rec["mbid"])

                # Update artist spotify_id if we don't have one
                artist_spotify = track.get("artists", [{}])[0].get("id")
                if artist_spotify and not rec["spotify_id"]:
                    await pg.execute("""
                        UPDATE music_artist
                        SET spotify_id = $1
                        WHERE mbid = $2 AND spotify_id IS NULL
                    """, artist_spotify, rec["artist_mbid"])

                track_ids_to_fetch.append((str(rec["mbid"]), spotify_track_id))
                stats["tracks_matched"] += 1
                print(f"  {rec['artist_name']} - {rec['title']} -> {spotify_track_id}")
            else:
                stats["tracks_failed"] += 1

        except Exception as e:
            print(f"  {rec['artist_name']} - {rec['title']} -> error: {e}")
            stats["tracks_failed"] += 1

    # Step 2b: Batch fetch audio features
    if track_ids_to_fetch:
        print(f"\nPass 2b: Fetching audio features for {len(track_ids_to_fetch)} tracks...")

        for i in range(0, len(track_ids_to_fetch), 100):
            batch = track_ids_to_fetch[i:i + 100]
            spotify_ids = [sid for _, sid in batch]
            mbid_map = {sid: mbid for mbid, sid in batch}

            try:
                features_list = sp.audio_features(spotify_ids)
                for feat in features_list:
                    if not feat:
                        continue
                    rec_mbid = mbid_map.get(feat["id"])
                    if not rec_mbid:
                        continue

                    await pg.execute("""
                        UPDATE music_recording SET
                            tempo = $1, energy = $2, valence = $3,
                            danceability = $4, acousticness = $5,
                            instrumentalness = $6, loudness_db = $7,
                            key = $8, mode = $9, time_signature = $10,
                            spotify_raw = $11, enriched_at = now(),
                            needs_refresh = false
                        WHERE mbid = $12
                    """,
                        feat.get("tempo"), feat.get("energy"), feat.get("valence"),
                        feat.get("danceability"), feat.get("acousticness"),
                        feat.get("instrumentalness"), feat.get("loudness"),
                        feat.get("key"), feat.get("mode"), feat.get("time_signature"),
                        json.dumps(feat), rec_mbid,
                    )
                    stats["features_fetched"] += 1

                print(f"  Batch {i // 100 + 1}: {len([f for f in features_list if f])} features")
            except Exception as e:
                print(f"  Batch {i // 100 + 1}: error: {e}")

    # Step 2c: Enrich artist genres/popularity from Spotify
    artists_needing_spotify = await pg.fetch("""
        SELECT mbid, name, spotify_id
        FROM music_artist
        WHERE spotify_id IS NOT NULL AND genres IS NULL
        LIMIT $1
    """, SPOTIFY_CAP)

    if artists_needing_spotify:
        print(f"\nPass 2c: Enriching {len(artists_needing_spotify)} artists from Spotify...")
        for art in artists_needing_spotify:
            try:
                sp_artist = sp.artist(art["spotify_id"])
                genres = sp_artist.get("genres", [])
                popularity = sp_artist.get("popularity")
                await pg.execute("""
                    UPDATE music_artist
                    SET genres = $1, spotify_popularity = $2, spotify_raw = $3
                    WHERE mbid = $4
                """, genres, popularity, json.dumps(sp_artist), art["mbid"])
            except Exception as e:
                print(f"  Artist {art['name']}: error: {e}")

    return stats


# ---------------------------------------------------------------------------
# Pass 3: Last.fm enrichment
# ---------------------------------------------------------------------------

LASTFM_RATE_INTERVAL = 0.25  # 4 req/s


async def pass3_lastfm(pg: asyncpg.Connection) -> dict:
    """Enrich artists with Last.fm tags, bio, and similar artists."""
    stats = {"artists_enriched": 0, "artists_failed": 0}

    if not LASTFM_API_KEY:
        print("Pass 3: Skipping Last.fm enrichment (no API key)")
        return stats

    import pylast

    network = pylast.LastFMNetwork(api_key=LASTFM_API_KEY)

    artists = await pg.fetch("""
        SELECT mbid, name
        FROM music_artist
        WHERE lastfm_raw IS NULL
          AND mbid IS NOT NULL
        LIMIT $1
    """, LASTFM_CAP)

    print(f"\nPass 3: Enriching {len(artists)} artists from Last.fm...")

    for art in artists:
        try:
            time.sleep(LASTFM_RATE_INTERVAL)
            lfm_artist = network.get_artist(art["name"])

            bio = None
            try:
                bio = lfm_artist.get_bio_summary()
                if bio:
                    # Strip HTML tags
                    import re
                    bio = re.sub(r"<[^>]+>", "", bio).strip()
                    if len(bio) > 500:
                        bio = bio[:497] + "..."
            except Exception:
                pass

            tags = []
            try:
                top_tags = lfm_artist.get_top_tags(limit=10)
                tags = [tag.item.name for tag in top_tags if tag.item]
            except Exception:
                pass

            raw = {"name": art["name"], "bio": bio, "tags": tags}

            await pg.execute("""
                UPDATE music_artist
                SET tags = $1, bio = $2, lastfm_raw = $3,
                    enriched_at = now(), needs_refresh = false
                WHERE mbid = $4
            """, tags or None, bio, json.dumps(raw), art["mbid"])

            stats["artists_enriched"] += 1
            tag_str = ", ".join(tags[:3]) if tags else "no tags"
            print(f"  {art['name']}: {tag_str}")

        except Exception as e:
            print(f"  {art['name']}: error: {e}")
            stats["artists_failed"] += 1

    return stats


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def run() -> None:
    pg = await asyncpg.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "scrobble"),
        password=os.environ["POSTGRES_PASSWORD"],
        database="scrobble",
    )

    try:
        # Ensure enrichment tables exist
        await pg.execute(SCHEMA_SQL)

        total_artists = await pg.fetchval("SELECT COUNT(DISTINCT name_lower) FROM artist")
        total_tracks = await pg.fetchval("SELECT COUNT(*) FROM track")
        resolved_artists = await pg.fetchval(
            "SELECT COUNT(DISTINCT artist_string) FROM music_scrobble_link WHERE artist_mbid IS NOT NULL"
        )
        resolved_tracks = await pg.fetchval(
            "SELECT COUNT(DISTINCT track_string) FROM music_scrobble_link WHERE recording_mbid IS NOT NULL"
        )
        print(f"Status: {resolved_artists}/{total_artists} artists, {resolved_tracks}/{total_tracks} tracks resolved")
        print("=" * 60)

        # Pass 1: MusicBrainz
        mb_stats = await pass1_musicbrainz(pg)
        print(f"\nPass 1 complete: {mb_stats}")

        # Pass 2: Spotify
        sp_stats = await pass2_spotify(pg)
        print(f"\nPass 2 complete: {sp_stats}")

        # Pass 3: Last.fm
        lfm_stats = await pass3_lastfm(pg)
        print(f"\nPass 3 complete: {lfm_stats}")

        # Final stats
        resolved_artists = await pg.fetchval(
            "SELECT COUNT(DISTINCT artist_string) FROM music_scrobble_link WHERE artist_mbid IS NOT NULL"
        )
        resolved_tracks = await pg.fetchval(
            "SELECT COUNT(DISTINCT track_string) FROM music_scrobble_link WHERE recording_mbid IS NOT NULL"
        )
        print(f"\nFinal: {resolved_artists}/{total_artists} artists, {resolved_tracks}/{total_tracks} tracks resolved")

    finally:
        await pg.close()


def main():
    hc_ping("/start")
    rc = 0
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        rc = 1
    hc_ping(f"/{rc}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
