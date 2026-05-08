from django.db import models
from cameras.models import Camera
from users.models import User
# Create your models here.
class VideoPrediction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="video_predictions", null=True, blank=True)
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, null=True, blank=True)
    video = models.FileField(upload_to="videos/")
    video_url = models.URLField(null=True, blank=True)
    
    final_result = models.CharField(max_length=20, null=True, blank=True)
    suspicious_frames = models.IntegerField(default=0)
    normal_frames = models.IntegerField(default=0)
    suspicious_frame_url = models.URLField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.id} - {self.final_result}"
