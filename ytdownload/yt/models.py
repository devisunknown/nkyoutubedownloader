# models.py
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class DownloadTicket(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"
        DOWNLOADED = "downloaded", "Downloaded"
        EXPIRED = "expired", "Expired"

    TICKET_TTL_SECONDS = 300

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    video_url = models.URLField(max_length=500)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Populated once yt-dlp finishes, so stream_download knows what to serve.
    filepath = models.CharField(max_length=1024, blank=True, default="")
    temp_dir = models.CharField(max_length=1024, blank=True, default="")
    download_name = models.CharField(max_length=300, blank=True, default="")
    error_message = models.CharField(max_length=500, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def is_expired(self) -> bool:
        return timezone.now() > self.created_at + timedelta(seconds=self.TICKET_TTL_SECONDS)

    def __str__(self):
        return f"{self.id} ({self.status})"