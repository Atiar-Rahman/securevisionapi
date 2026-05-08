# api/urls.py
from rest_framework.routers import DefaultRouter
from django.urls import path
from cameras.views import CameraViewSet, CameraListViewSet
from detection.views import DetectAPIView, DetectAPIViewUpdate, DetectAPIView14,DetectAPIViewSikp,VideoPredictionViewSet,Detect3DCNNAPIView
from alert.views import AlertViewSet
from contact.views import ContactModelViewSet
from reviews.views import ReviewViewSet
from api.views import warmup_models


router = DefaultRouter()
# Camera CRUD API
router.register('cameras', CameraViewSet, basename='cameras')
# Optional: Only list cameras for dropdown
router.register('camera-list', CameraListViewSet, basename='camera-list')
# alert CRUD API
router.register('alerts',AlertViewSet,basename='alert')
# contact Crud API
router.register('contact',ContactModelViewSet,basename='contact')
router.register('reviews', ReviewViewSet, basename='reviews')
# video upload url
router.register("video-predictions", VideoPredictionViewSet, basename="video-pred")

urlpatterns = [
    # Legacy multi-frame API (optional)
    path("detect/", DetectAPIView14.as_view(), name="detect14"),

    # Single-frame per camera with user validation
    path("detect-update/", DetectAPIViewUpdate.as_view(), name="detect-update"),

    # Production-ready detection API (multi-camera safe)
    path("detection/", DetectAPIView.as_view(), name="detection"),
    path('detection-skip/',DetectAPIViewSikp.as_view(),name='frame-skip'),
    path('detection-3dcnn/',Detect3DCNNAPIView.as_view(),name='frame-3d'),
    path("warmup/", warmup_models, name="warmup-models"),
]

# Include router URLs (Camera CRUD + Camera list)
urlpatterns += router.urls
