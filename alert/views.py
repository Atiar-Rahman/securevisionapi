from django.utils.dateparse import parse_date
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.exceptions import ValidationError
from rest_framework.viewsets import ModelViewSet
from api.permissions import IsAuthenticatedWithAdminFullAccess, has_full_access
from alert.models import Alert
from alert.serializers import AlertSerializer

class AlertViewSet(ModelViewSet):
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticatedWithAdminFullAccess]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["alert_type", "camera__name", "user__email"]
    ordering_fields = ["created_at", "confidence", "alert_type"]
    ordering = ["-created_at"]


    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Alert.objects.none()

        if has_full_access(self.request.user):
            queryset = Alert.objects.select_related("user", "camera")
        else:
            queryset = Alert.objects.filter(user=self.request.user).select_related("user", "camera")

        date_value = self.request.query_params.get("date")
        if date_value:
            parsed_date = parse_date(date_value)
            if parsed_date is None:
                raise ValidationError({"date": "Invalid date format. Use YYYY-MM-DD."})
            queryset = queryset.filter(created_at__date=parsed_date)

        return queryset
    
    def perform_create(self, serializer):
        serializer.save(user = self.request.user)
