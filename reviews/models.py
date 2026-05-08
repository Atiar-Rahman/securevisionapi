from django.db import models
from django.core.validators import MinValueValidator,MaxValueValidator
# Create your models here.
class Reviews(models.Model):
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='views')
    title = models.CharField(max_length=150)
    rating = models.IntegerField(validators=[MinValueValidator(1),MaxValueValidator(5)])
    comments = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.email

