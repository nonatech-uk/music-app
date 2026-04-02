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

import httpx

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

SPOTIFY_TOKEN_PROXY_URL = os.environ.get("SPOTIFY_TOKEN_PROXY_URL", "")
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "")

MUSICBRAINZ_TOKEN = os.environ.get("MUSICBRAINZ_TOKEN", "")

musicbrainzngs.set_useragent("PIF-Enricher", "1.0", "stu@mees.st")
if MUSICBRAINZ_TOKEN:
    musicbrainzngs.auth(MUSICBRAINZ_TOKEN, MUSICBRAINZ_TOKEN)
    musicbrainzngs.set_hostname("musicbrainz.org", use_https=True)


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
    resolution_attempts smallint DEFAULT 0,
    resolved_at     timestamptz,
    reviewed_at     timestamptz,
    manual_override boolean DEFAULT false,
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
# Pass 0: Library tag harvesting
# ---------------------------------------------------------------------------

LIBRARY_PATH = os.environ.get("MUSIC_LIBRARY_PATH", "")
LIBRARY_SCAN_CAP = int(os.environ.get("LIBRARY_SCAN_CAP", "0"))  # 0 = unlimited

import re
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

def _valid_uuid(s: str | None) -> str | None:
    """Return the string if it's a valid UUID, else None."""
    if s and _UUID_RE.match(s):
        return s
    return None


async def pass0_library_tags(pg: asyncpg.Connection) -> dict:
    """Harvest MusicBrainz IDs from embedded file tags and backfill scrobble links."""
    if not LIBRARY_PATH or not os.path.isdir(LIBRARY_PATH):
        print("Pass 0: Skipped (MUSIC_LIBRARY_PATH not set or not found)")
        return {"scanned": 0, "matched": 0, "skipped": 0}

    from mutagen import File as MutagenFile

    stats = {"scanned": 0, "matched": 0, "skipped": 0, "artists_seeded": 0}

    # Get last scan timestamp (stored as an app_setting-style row in a small table)
    await pg.execute("""
        CREATE TABLE IF NOT EXISTS enrichment_state (
            key text PRIMARY KEY,
            value text NOT NULL
        )
    """)
    last_scan_row = await pg.fetchval(
        "SELECT value FROM enrichment_state WHERE key = 'library_scan_mtime'"
    )
    last_scan_mtime = float(last_scan_row) if last_scan_row else 0.0

    max_mtime = last_scan_mtime
    scanned = 0

    print(f"Pass 0: Scanning library tags from {LIBRARY_PATH}")
    if last_scan_mtime:
        from datetime import datetime
        print(f"  Only files modified after {datetime.fromtimestamp(last_scan_mtime).isoformat()}")

    for root, _dirs, files in os.walk(LIBRARY_PATH):
        for fname in files:
            if not fname.endswith(('.m4a', '.flac', '.mp3')):
                continue

            fpath = os.path.join(root, fname)
            try:
                mtime = os.path.getmtime(fpath)
            except OSError:
                continue

            if mtime <= last_scan_mtime:
                stats["skipped"] += 1
                continue

            if LIBRARY_SCAN_CAP and scanned >= LIBRARY_SCAN_CAP:
                break

            if mtime > max_mtime:
                max_mtime = mtime

            try:
                f = MutagenFile(fpath)
                if not f or not f.tags:
                    continue
            except Exception:
                continue

            scanned += 1
            tags = f.tags

            # Extract MBIDs from tags (M4A freeform atoms, ID3 TXXX, Vorbis comments)
            track_mbid = None
            artist_mbid = None
            for k in tags.keys():
                kl = str(k).lower()
                if 'musicbrainz track id' in kl:
                    v = tags[k]
                    if isinstance(v, list):
                        v = v[0]
                    track_mbid = str(v).strip("b'\"")
                elif 'musicbrainz artist id' in kl:
                    v = tags[k]
                    if isinstance(v, list):
                        v = v[0]
                    artist_mbid = str(v).strip("b'\"")

            track_mbid = _valid_uuid(track_mbid)
            artist_mbid = _valid_uuid(artist_mbid)
            if not track_mbid and not artist_mbid:
                continue

            # Extract basic tags for matching against scrobble link strings
            artist_name = None
            track_title = None
            for label, keys in [
                ('artist', ['\xa9ART', 'TPE1', 'artist']),
                ('title', ['\xa9nam', 'TIT2', 'title']),
            ]:
                for tk in keys:
                    try:
                        v = tags[tk]
                        if isinstance(v, list):
                            v = v[0]
                        if label == 'artist':
                            artist_name = str(v)
                        else:
                            track_title = str(v)
                        break
                    except (KeyError, ValueError, IndexError):
                        continue

            if not artist_name or not track_title:
                continue

            artist_lower = artist_name.lower()
            track_lower = track_title.lower()

            # Try to match against existing scrobble link
            link = await pg.fetchrow("""
                SELECT id, artist_mbid, recording_mbid, manual_override
                FROM music_scrobble_link
                WHERE artist_string = $1 AND track_string = $2
            """, artist_lower, track_lower)

            if not link:
                continue  # No scrobble for this file
            if link["manual_override"]:
                continue  # Don't overwrite manual links
            if link["recording_mbid"] is not None:
                continue  # Already resolved

            # Ensure artist exists in music_artist
            if artist_mbid:
                existing_artist = await pg.fetchval(
                    "SELECT mbid FROM music_artist WHERE mbid = $1::uuid", artist_mbid
                )
                if not existing_artist:
                    await pg.execute("""
                        INSERT INTO music_artist (mbid, name, created_at)
                        VALUES ($1::uuid, $2, now())
                        ON CONFLICT (mbid) DO NOTHING
                    """, artist_mbid, artist_name)
                    stats["artists_seeded"] += 1

            # Ensure recording exists in music_recording
            if track_mbid and artist_mbid:
                await pg.execute("""
                    INSERT INTO music_recording (mbid, artist_mbid, title, created_at)
                    VALUES ($1::uuid, $2::uuid, $3, now())
                    ON CONFLICT (mbid) DO NOTHING
                """, track_mbid, artist_mbid, track_title)

            # Update the scrobble link
            if track_mbid and artist_mbid:
                await pg.execute("""
                    UPDATE music_scrobble_link
                    SET artist_mbid = $1::uuid, recording_mbid = $2::uuid,
                        resolution_method = 'file_tag', resolution_score = 1.0, resolved_at = now()
                    WHERE id = $3
                """, artist_mbid, track_mbid, link["id"])
                stats["matched"] += 1
                print(f"  Tag: {artist_name} - {track_title} -> linked from file")
            elif artist_mbid and not link["artist_mbid"]:
                await pg.execute("""
                    UPDATE music_scrobble_link
                    SET artist_mbid = $1::uuid, resolution_score = 1.0
                    WHERE id = $2
                """, artist_mbid, link["id"])

    stats["scanned"] = scanned

    # Save high-water mark
    if max_mtime > last_scan_mtime:
        await pg.execute("""
            INSERT INTO enrichment_state (key, value) VALUES ('library_scan_mtime', $1)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, str(max_mtime))

    return stats


# ---------------------------------------------------------------------------
# Pass 0.5: Claude-assisted MusicBrainz disambiguation
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_CAP = int(os.environ.get("CLAUDE_CAP", "100"))  # max items per run


async def _claude_pick_recording(
    http: httpx.AsyncClient,
    artist_name: str,
    track_title: str,
    album_title: str | None,
    candidates: list[dict],
) -> dict | None:
    """Ask Claude to pick the best MusicBrainz recording match."""
    if not candidates:
        return None

    candidate_lines = []
    for i, c in enumerate(candidates):
        releases = c.get("release-list", [])
        release_info = ""
        if releases:
            albums = [r.get("title", "") for r in releases[:3]]
            release_info = f" (albums: {', '.join(albums)})"
        artists = "; ".join(
            a.get("name", "") for a in c.get("artist-credit", []) if isinstance(a, dict)
        )
        candidate_lines.append(
            f"  {i+1}. \"{c.get('title', '')}\" by {artists} [MBID: {c['id']}]{release_info}"
        )

    album_hint = f"\nAlbum context: \"{album_title}\"" if album_title else ""

    prompt = f"""Match this scrobbled track to the correct MusicBrainz recording.

Scrobble: "{artist_name}" - "{track_title}"{album_hint}

Candidates:
{chr(10).join(candidate_lines)}

Key matching rules:
- Scrobble titles are often SHORTENED or use COMMON NAMES. "Time of Your Life" IS "Good Riddance (Time of Your Life)". "Baker Street" IS "Baker Street".
- Parenthetical extras like (Remastered), (Live), (Radio Edit) are usually fine — match the base song.
- Cover versions performed by the scrobbled artist ARE valid matches.
- Multi-part tracks with slashes (e.g. "A / B / C") may match a single combined recording.
- Abbreviations: "ISHFWILF" could be "I Still Haven't Found What I'm Looking For".
- Only say "none" if the song genuinely isn't in the candidates at all or the artist is completely wrong.

Reply with ONLY the number or "none"."""

    body = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 5,
        "temperature": 0,
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "My answer is:"},
        ],
    }
    resp = await http.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data["content"][0]["text"].strip().lower()

    # Extract number from answer — handle " 2", "2.", "2\n", etc.
    answer = answer.strip()
    if "none" in answer:
        return None
    # Find first number in the answer
    m = re.search(r'\d+', answer)
    if m:
        idx = int(m.group()) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]
    return None


async def pass05_claude_disambiguation(pg: asyncpg.Connection) -> dict:
    """Use Claude to resolve recordings that fuzzy matching missed."""
    if not ANTHROPIC_API_KEY:
        print("Pass 0.5: Skipped (ANTHROPIC_API_KEY not set)")
        return {"resolved": 0, "failed": 0, "skipped": 0}

    stats = {"resolved": 0, "failed": 0, "skipped": 0}

    # Get unresolved recordings with artist MBID, ordered by play count
    rows = await pg.fetch("""
        SELECT sl.id AS link_id, sl.track_string, sl.artist_string, sl.artist_mbid,
               t.title, t.album_title, a.name AS artist_name, sl.track_id,
               (SELECT COUNT(*) FROM scrobble s WHERE s.track_id = sl.track_id) AS play_count
        FROM music_scrobble_link sl
        JOIN track t ON t.id = sl.track_id
        JOIN artist a ON a.id = sl.artist_id
        WHERE sl.artist_mbid IS NOT NULL
          AND sl.recording_mbid IS NULL
          AND NOT COALESCE(sl.manual_override, false)
        ORDER BY play_count DESC
        LIMIT $1
    """, CLAUDE_CAP)

    if not rows:
        print("Pass 0.5: No unresolved recordings to process")
        return stats

    print(f"Pass 0.5: Claude disambiguation for {len(rows)} recordings...")

    async with httpx.AsyncClient() as http:
        for row in rows:
            artist_name = row["artist_name"]
            track_title = row["title"]
            album_title = row["album_title"]

            # Search MusicBrainz for candidates (broader search, more results)
            try:
                result = mb_search_recordings(track_title, artist_name, limit=10)
                candidates = result.get("recording-list", [])
            except Exception as e:
                print(f"  MB search error for {artist_name} - {track_title}: {e}")
                stats["skipped"] += 1
                continue

            if not candidates:
                stats["failed"] += 1
                continue

            # Ask Claude to pick
            try:
                pick = await _claude_pick_recording(
                    http, artist_name, track_title, album_title, candidates
                )
            except Exception as e:
                print(f"  Claude error for {artist_name} - {track_title}: {e}")
                stats["skipped"] += 1
                continue

            if pick:
                recording_mbid = pick["id"]
                recording_title = pick.get("title", "")

                # Get artist MBID from the candidate
                candidate_artist_mbid = None
                for ac in pick.get("artist-credit", []):
                    if isinstance(ac, dict) and ac.get("artist", {}).get("id"):
                        candidate_artist_mbid = ac["artist"]["id"]
                        break

                artist_mbid = str(row["artist_mbid"])

                # Upsert recording
                isrc = None
                rg_mbid = None
                releases = pick.get("release-list", [])
                if releases:
                    r0 = releases[0]
                    rg = r0.get("release-group", {})
                    if rg.get("id"):
                        rg_mbid = await _upsert_release_group(pg, rg, artist_mbid)

                duration_ms = None
                raw_length = pick.get("length")
                if raw_length is not None:
                    try:
                        duration_ms = int(raw_length)
                    except (ValueError, TypeError):
                        pass

                await pg.execute("""
                    INSERT INTO music_recording (mbid, artist_mbid, title, release_group_mbid, duration_ms, isrc, mb_raw, created_at)
                    VALUES ($1::uuid, $2::uuid, $3, $4::uuid, $5, $6, $7, now())
                    ON CONFLICT (mbid) DO NOTHING
                """, recording_mbid, artist_mbid, recording_title,
                    rg_mbid, duration_ms, isrc, json.dumps(pick))

                # Update the scrobble link
                await pg.execute("""
                    UPDATE music_scrobble_link
                    SET recording_mbid = $1::uuid, resolution_method = 'claude',
                        resolution_score = 0.95, resolved_at = now()
                    WHERE id = $2
                """, recording_mbid, row["link_id"])
                stats["resolved"] += 1
                print(f"  Claude: {artist_name} - {track_title} -> {recording_title} ({recording_mbid[:8]}...)")
            else:
                # Mark as failed so we don't re-process
                await pg.execute("""
                    UPDATE music_scrobble_link
                    SET resolution_method = 'claude_failed', resolved_at = now(),
                        resolution_attempts = COALESCE(resolution_attempts, 0) + 1
                    WHERE id = $1
                """, row["link_id"])
                stats["failed"] += 1
                print(f"  Claude: {artist_name} - {track_title} -> no match")

    return stats


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
          AND NOT COALESCE(sl.manual_override, false)
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
          AND NOT COALESCE(sl.manual_override, false)
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
# Pass 2: Spotify enrichment (via token proxy)
# ---------------------------------------------------------------------------

class SpotifyClient:
    """Thin Spotify Web API client that gets tokens from the token proxy."""

    SPOTIFY_API = "https://api.spotify.com/v1"

    def __init__(self, token_proxy_url: str):
        self._proxy_url = token_proxy_url.rstrip("/")
        self._client = httpx.Client(timeout=15)
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _ensure_token(self):
        if self._token and time.time() < self._token_expires_at - 30:
            return
        resp = self._client.get(f"{self._proxy_url}/token/user")
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)

    def _headers(self) -> dict:
        self._ensure_token()
        return {"Authorization": f"Bearer {self._token}"}

    def search(self, q: str, type: str = "track", limit: int = 1) -> dict:
        time.sleep(0.1)  # rate limiting
        resp = self._client.get(
            f"{self.SPOTIFY_API}/search",
            params={"q": q, "type": type, "limit": limit},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def artist(self, artist_id: str) -> dict:
        time.sleep(0.1)
        resp = self._client.get(
            f"{self.SPOTIFY_API}/artists/{artist_id}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def audio_features(self, track_ids: list[str]) -> list[dict | None]:
        """Fetch audio features — handles 403 (deprecated endpoint) gracefully."""
        try:
            resp = self._client.get(
                f"{self.SPOTIFY_API}/audio-features",
                params={"ids": ",".join(track_ids)},
                headers=self._headers(),
            )
            if resp.status_code == 403:
                print("  Audio features endpoint returned 403 (deprecated), skipping")
                return []
            resp.raise_for_status()
            return resp.json().get("audio_features", [])
        except httpx.HTTPStatusError:
            return []

    def close(self):
        self._client.close()


async def pass2_spotify(pg: asyncpg.Connection) -> dict:
    """Enrich recordings with Spotify track IDs and audio features."""
    stats = {"tracks_matched": 0, "tracks_failed": 0, "features_fetched": 0}

    if not SPOTIFY_TOKEN_PROXY_URL:
        print("Pass 2: Skipping Spotify enrichment (no token proxy URL)")
        return stats

    sp = SpotifyClient(SPOTIFY_TOKEN_PROXY_URL)

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

    sp.close()
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

        # Pass 0: Library tag harvesting
        lib_stats = await pass0_library_tags(pg)
        print(f"\nPass 0 complete: {lib_stats}")

        # Pass 0.5: Claude disambiguation
        claude_stats = await pass05_claude_disambiguation(pg)
        print(f"\nPass 0.5 complete: {claude_stats}")

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
