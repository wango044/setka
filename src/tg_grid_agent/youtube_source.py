from __future__ import annotations

import re
import urllib.parse


def extract_youtube_video_id(url_or_id: str) -> str:
    value = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    parsed = urllib.parse.urlparse(value)
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return video_id

    if host.endswith("youtube.com"):
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("v"):
            video_id = query["v"][0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return video_id

        path_parts = [part for part in parsed.path.split("/") if part]
        for marker in ("shorts", "embed", "live"):
            if marker in path_parts:
                index = path_parts.index(marker) + 1
                if index < len(path_parts):
                    video_id = path_parts[index]
                    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                        return video_id

    raise ValueError(f"Cannot find a YouTube video id in: {url_or_id}")


def fetch_youtube_transcript(url_or_id: str, languages: tuple[str, ...] = ("ru", "en")) -> str:
    video_id = extract_youtube_video_id(url_or_id)
    transcript = _fetch_transcript(video_id, languages)
    text = " ".join(_snippet_text(snippet) for snippet in transcript)
    return re.sub(r"\s+", " ", text).strip()


def _fetch_transcript(video_id: str, languages: tuple[str, ...]):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise RuntimeError("Install dependencies first: pip install -e .") from exc

    try:
        return YouTubeTranscriptApi.get_transcript(video_id, languages=list(languages))
    except AttributeError:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=list(languages))
        return fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched


def _snippet_text(snippet) -> str:
    if isinstance(snippet, dict):
        return str(snippet.get("text", ""))
    return str(getattr(snippet, "text", ""))
