import os
import re
import shutil
import tempfile
import logging

import yt_dlp

from django.core.cache import cache          
from django.shortcuts import render, redirect
from django.http import FileResponse, HttpResponseBadRequest, Http404
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from django_ratelimit.decorators import ratelimit

from .models import DownloadTicket



logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
}

MAX_FILESIZE = 200 * 1024 * 1024  # 200MB cap, tune to your disk budget


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
        super().__init__(open(filepath, 'rb'), **kwargs)

    def close(self):
        super().close()
        try:
            shutil.rmtree(self._temp_dir, ignore_errors=False)
        except Exception:
            logger.exception("Failed to clean up temp dir %s", self._temp_dir)


def index(request):
    if request.method == "POST":
        return _handle_download(request)
    return render(request, "index.html")


@ratelimit(key='ip', rate='7/m', block=True)
def _handle_download(request):
    video_url = request.POST.get("video_url", "").strip()

    if not video_url:
        return HttpResponseBadRequest("Please provide a valid YouTube link.")

    if not _is_allowed_youtube_url(video_url):
        return render(request, "index.html", {
            "error": "Please provide a valid YouTube link."
        })

    temp_dir = tempfile.mkdtemp(prefix="ytdl_")
    output_template = os.path.join(temp_dir, "%(id)s.%(ext)s")

    ydl_opts = {
        'format': 'best',
        'outtmpl': output_template,
        'noplaylist': True,
        'restrictfilenames': True,
        'max_filesize': MAX_FILESIZE,
        'quiet': True,
        'no_warnings': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filepath = ydl.prepare_filename(info)

        if not os.path.exists(filepath):
            raise FileNotFoundError("Downloaded file not found after extraction.")

        
        title = info.get("title") or "video"
        ext = os.path.splitext(filepath)[1]
        safe_download_name = re.sub(r'[\\/*?:"<>|]', "_", title)[:150] + ext

        return DeleteAfterStreamFileResponse(
            filepath,
            temp_dir,
            as_attachment=True,
            filename=safe_download_name,
        )

    except Exception:
        logger.exception("yt-dlp download failed for url=%s", video_url)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return render(request, "index.html", {
            "error": "Sorry, that video couldn't be downloaded. "
                     "Check the link and try again."
        })


def done(request):
    return render(request, "done.html")



from .models import DownloadTicket

def _handle_download(request):
    video_url = request.POST.get("video_url", "").strip()

    if not video_url:
        return HttpResponseBadRequest("Please provide a valid YouTube link.")
    if not _is_allowed_youtube_url(video_url):
        return render(request, "index.html", {"error": "Please provide a valid YouTube link."})

    ticket = DownloadTicket.objects.create(
        user=request.user if request.user.is_authenticated else None,
        video_url=video_url,
    )

    temp_dir = tempfile.mkdtemp(prefix="ytdl_")
    output_template = os.path.join(temp_dir, "%(id)s.%(ext)s")
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_template,
        'noplaylist': True,
        'restrictfilenames': True,
        'max_filesize': MAX_FILESIZE,
        'quiet': True,
        'no_warnings': True,
    }

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

    return _DeleteAfterStreamFileResponse(
        ticket.filepath,
        ticket.temp_dir,
        as_attachment=True,
        filename=ticket.download_name,
    )