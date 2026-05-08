from django.urls import re_path
from detection import consumers

websocket_urlpatterns = [
    re_path(r"ws/detect/$", consumers.DetectionConsumer.as_asgi()),
]
