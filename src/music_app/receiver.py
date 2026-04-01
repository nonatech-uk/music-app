"""Entrypoint for the music-app container."""

import uvicorn

from music_app.api.app import app


def main():
    uvicorn.run(app, host="0.0.0.0", port=42010, log_level="info")


if __name__ == "__main__":
    main()
