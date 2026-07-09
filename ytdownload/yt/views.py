import os
import tempfile
from django.shortcuts import render
from django.http import FileResponse, HttpResponseBadRequest
from django_ratelimit.decorators import ratelimit
import yt_dlp


class DeleteAfterStreamFileResponse(FileResponse):
    def __init__(self, filepath, **kwargs):
        self._filepath = filepath
        super().__init__(open(filepath, 'rb'), **kwargs)

    def close(self):
        super().close()
        try:
            os.remove(self._filepath)
        except Exception:
            pass


@ratelimit(key='ip', rate='7/m', block=True)
def index(request):
    if request.method == "POST":
        video_url = request.POST.get("video_url")

        if not video_url:
            return HttpResponseBadRequest("Please provide a valid YouTube link.")

        temp_dir = tempfile.gettempdir()
        output_template = os.path.join(temp_dir, "%(title)s.%(ext)s")

        ydl_opts = {
            'format': 'best',
            'outtmpl': output_template,
            'noplaylist': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                filename = ydl.prepare_filename(info)

            return DeleteAfterStreamFileResponse(
                filename,
                as_attachment=True,
                filename=os.path.basename(filename)
            )

        except Exception as e:
            return render(request, "index.html", {"error": f"Download failed: {str(e)}"})

    return render(request, "index.html")


def done(request):
    return render(request, "done.html")