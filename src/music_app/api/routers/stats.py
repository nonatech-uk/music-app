"""Overview statistics endpoint."""

from fastapi import APIRouter, Depends

from music_app.api.deps import dict_cursor, get_conn

router = APIRouter()


@router.get("/stats/overview")
def overview(conn=Depends(get_conn)):
    cur = dict_cursor(conn)

    cur.execute("SELECT count(*) AS c FROM track")
    total_tracks = cur.fetchone()["c"]

    cur.execute("SELECT count(*) AS c FROM artist")
    total_artists = cur.fetchone()["c"]

    cur.execute("SELECT count(*) AS c FROM scrobble WHERE listened_at::date = CURRENT_DATE")
    scrobbles_today = cur.fetchone()["c"]

    cur.execute("""
        SELECT a.name
        FROM scrobble s
        JOIN track_artist ta ON ta.track_id = s.track_id
        JOIN artist a ON a.id = ta.artist_id
        WHERE s.listened_at >= now() - interval '7 days'
        GROUP BY a.name
        ORDER BY count(*) DESC
        LIMIT 1
    """)
    top_row = cur.fetchone()

    return {
        "total_tracks": total_tracks,
        "total_artists": total_artists,
        "scrobbles_today": scrobbles_today,
        "top_artist": top_row["name"] if top_row else None,
    }
