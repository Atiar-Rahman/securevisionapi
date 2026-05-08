from django.db import models
from django.contrib.auth import get_user_model
from cameras.models import Camera
# Create your models here.

User = get_user_model()

class Alert(models.Model):
    user = models.ForeignKey(User,on_delete=models.CASCADE,related_name='alert')
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE,related_name='alert')

    alert_type = models.CharField(max_length=50)
    confidence = models.FloatField()
    frame_url = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.alert_type} - {self.confidence}'
    
    
