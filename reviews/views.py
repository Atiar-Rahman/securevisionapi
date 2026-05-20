from rest_framework.viewsets import ModelViewSet

from api.permissions import IsAuthenticatedWithAdminFullAccess, has_full_access
from reviews.models import Reviews
from reviews.serializers import ReviewSerializer


class ReviewViewSet(ModelViewSet):
    serializer_class = ReviewSerializer
    permission_classes = [IsAuthenticatedWithAdminFullAccess]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Reviews.objects.none()

        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return Reviews.objects.none()

        queryset = Reviews.objects.select_related("user").order_by("-created_at")
        if has_full_access(self.request.user):
            return queryset
        return queryset.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
