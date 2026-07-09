import os
import re
import shutil
import tempfile
import logging
from urllib.parse import urlparse

import yt_dlp

from django.shortcuts import render, redirect
from django.http import FileResponse, HttpResponseBadRequest, Http404
from django.urls import reverse

from django_ratelimit.decorators import ratelimit

from .models import DownloadTicket

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
}

MAX_FILESIZE = 200 * 1024 * 1024  


COOKIE_FILE = os.environ.get("COOKIE_FILE") or next(
    (p for p in (
        "/etc/secrets/cookies.txt",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "cookies.txt"),
    ) if os.path.exists(p)),
    "/etc/secrets/cookies.txt", 
)


def _is_allowed_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in ALLOWED_HOSTS


class DeleteAfterStreamFileResponse(FileResponse):
    """Streams a file then deletes its entire temp directory, not just the file."""

    def __init__(self, filepath, temp_dir, **kwargs):
        self._temp_dir = temp_dir
        super().__init__(open(filepath, "rb"), **kwargs)

    def close(self):
        super().close()
        try:
            shutil.rmtree(self._temp_dir, ignore_errors=False)
        except Exception:
            logger.exception("Failed to clean up temp dir %s", self._temp_dir)


def _build_ydl_opts(output_template: str) -> dict:
    opts = {
        "format": "best",
        "outtmpl": output_template,
        "noplaylist": True,
        "restrictfilenames": True,
        "max_filesize": MAX_FILESIZE,
        "quiet": True,
        "no_warnings": True,
    }
    
    
    if os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE
    else:
        logger.warning(
            "No cookies file found at %s — YouTube requests will go out "
            "unauthenticated and may be blocked with a bot-check error.",
            COOKIE_FILE,
        )
    return opts


def done(request):
    return render(request, "done.html")


@ratelimit(key="ip", rate="7/m", block=True)
def index(request):
    if request.method == "POST":
        return handle_download(request)
    return render(request, "index.html")


def handle_download(request):
    video_url = request.POST.get("video_url", "").strip()

    if not video_url:
        return HttpResponseBadRequest("Please provide a valid YouTube link.")
    if not _is_allowed_youtube_url(video_url):
        return render(request, "index.html", {
            "error": "Please provide a valid YouTube link."
        })

    ticket = DownloadTicket.objects.create(
        user=request.user if request.user.is_authenticated else None,
        video_url=video_url,
    )

    temp_dir = tempfile.mkdtemp(prefix="ytdl_")
    output_template = os.path.join(temp_dir, "%(id)s.%(ext)s")
    ydl_opts = _build_ydl_opts(output_template)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filepath = ydl.prepare_filename(info)

        if not os.path.exists(filepath):
            raise FileNotFoundError("Downloaded file not found after extraction.")

        title = info.get("title") or "video"
        ext = os.path.splitext(filepath)[1]
        download_name = re.sub(r'[\\/*?:"<>|]', "_", title)[:150] + ext

        ticket.filepath = filepath
        ticket.temp_dir = temp_dir
        ticket.download_name = download_name
        ticket.status = DownloadTicket.Status.READY
        ticket.save()

        return redirect(reverse("deletestreamfile", args=[ticket.id]))

    except Exception:
        logger.exception("yt-dlp download failed for url=%s", video_url)
        shutil.rmtree(temp_dir, ignore_errors=True)
        ticket.status = DownloadTicket.Status.FAILED
        ticket.error_message = "Download failed."
        ticket.save()
        return render(request, "index.html", {
            "error": "Sorry, that video couldn't be downloaded. Check the link and try again."
        })


def stream_download(request, ticket_id):
    try:
        ticket = DownloadTicket.objects.get(id=ticket_id, status=DownloadTicket.Status.READY)
    except DownloadTicket.DoesNotExist:
        raise Http404("This download link has expired or was already used.")

    if ticket.is_expired() or not os.path.exists(ticket.filepath):
        ticket.status = DownloadTicket.Status.EXPIRED
        ticket.save()
        shutil.rmtree(ticket.temp_dir, ignore_errors=True)
        raise Http404("This download link has expired.")

    ticket.status = DownloadTicket.Status.DOWNLOADED
    ticket.save()

    return DeleteAfterStreamFileResponse(
        ticket.filepath,
        ticket.temp_dir,
        as_attachment=True,
        filename=ticket.download_name,
    )