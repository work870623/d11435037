from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

from flask import Flask, jsonify, render_template


app = Flask(__name__, template_folder=".")

HTTP_TIMEOUT = 5
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) learning-video-fetcher/1.0"
PLAYLIST_ID = "PLBcMyiCni2F9gLqAI8iImMQyt4LTm5fNY"


@dataclass(frozen=True)
class LessonVideo:
    unit: int
    title: str
    query: str
    youtube_url: str | None = None


LESSON_VIDEOS = [
    LessonVideo(
        unit=1,
        title="第一章 會計基本概念",
        query="會計學入門 第一章 會計基本概念",
        youtube_url="https://www.youtube.com/watch?v=0NkMCvR0XsI",
    ),
    LessonVideo(
        unit=2,
        title="第二章 會計理論與主要財務報表",
        query="會計學入門 第二章 會計理論 主要財務報表",
    ),
    LessonVideo(
        unit=3,
        title="第三章 會計處理六大程序 上",
        query="會計學入門 第三章 會計處理程序 分錄 日記帳 過帳",
    ),
    LessonVideo(
        unit=4,
        title="第四章 會計處理六大程序 下",
        query="會計學入門 第四章 試算 調整 結帳 編表",
    ),
]


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=HTTP_TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def video_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be"}:
        return parsed.path.strip("/") or None
    if parsed.hostname and "youtube.com" in parsed.hostname:
        query = parse_qs(parsed.query)
        if query.get("v"):
            return query["v"][0]
        match = re.search(r"/embed/([\w-]{11})", parsed.path)
        if match:
            return match.group(1)
    return None


def youtube_embed_url(video_id: str | None) -> str:
    player_params = "rel=0&modestbranding=1&playsinline=1"
    if video_id:
        return f"https://www.youtube.com/embed/{video_id}?{player_params}"
    return f"https://www.youtube.com/embed?listType=playlist&list={PLAYLIST_ID}&{player_params}"


def youtube_watch_url(video_id: str | None) -> str:
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return f"https://www.youtube.com/playlist?list={PLAYLIST_ID}"


def fetch_youtube_oembed(video_url: str) -> dict[str, str] | None:
    endpoint = "https://www.youtube.com/oembed?" + urlencode({"url": video_url, "format": "json"})
    try:
        return json.loads(fetch_text(endpoint))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def search_youtube_video(query: str) -> dict[str, str] | None:
    search_url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
    try:
        page = fetch_text(search_url)
    except (HTTPError, URLError, TimeoutError, OSError):
        return None

    ids = re.findall(r'"videoId":"([\w-]{11})"', page)
    video_id = next((item for item in ids if item), None)
    if not video_id:
        return None

    watch_url = youtube_watch_url(video_id)
    oembed = fetch_youtube_oembed(watch_url) or {}
    return {
        "title": unescape(oembed.get("title") or query),
        "watch_url": watch_url,
        "embed_url": youtube_embed_url(video_id),
        "source_label": "YouTube",
        "status": "已由 YouTube 即時搜尋更新",
    }


def search_fallback_course(query: str) -> dict[str, str] | None:
    search_url = "https://duckduckgo.com/html/?" + urlencode({"q": query + " 會計 課程"})
    try:
        page = fetch_text(search_url)
    except (HTTPError, URLError, TimeoutError, OSError):
        return None

    match = re.search(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.S)
    if not match:
        return None

    title = re.sub(r"<.*?>", "", match.group(2))
    return {
      "title": unescape(title).strip() or query,
      "watch_url": unescape(match.group(1)),
      "embed_url": youtube_embed_url(None),
      "source_label": "其他課程網站",
      "status": "YouTube 無法使用，已提供外部課程搜尋結果",
    }


def resolve_lesson_video(lesson: LessonVideo) -> dict[str, str | int]:
    video_id = video_id_from_url(lesson.youtube_url or "")
    if lesson.youtube_url and video_id:
        oembed = fetch_youtube_oembed(lesson.youtube_url)
        if oembed:
            return {
                "unit": lesson.unit,
                "title": unescape(oembed.get("title") or lesson.title),
                "watch_url": lesson.youtube_url,
                "embed_url": youtube_embed_url(video_id),
                "source_label": "YouTube",
                "status": "已由 YouTube 即時資訊更新",
            }

    youtube_result = search_youtube_video(lesson.query)
    if youtube_result:
        return {"unit": lesson.unit, **youtube_result}

    fallback_result = search_fallback_course(lesson.query)
    if fallback_result:
        return {"unit": lesson.unit, **fallback_result}

    return {
        "unit": lesson.unit,
        "title": lesson.title,
        "watch_url": youtube_watch_url(video_id),
        "embed_url": youtube_embed_url(video_id),
        "source_label": "內建備用課程",
        "status": "外部來源暫時無法連線，已使用預設影片",
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/videos")
def api_videos():
    videos = [resolve_lesson_video(lesson) for lesson in LESSON_VIDEOS]
    return jsonify({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "videos": videos,
    })


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000, use_reloader=False)
