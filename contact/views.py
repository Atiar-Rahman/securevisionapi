from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.viewsets import ModelViewSet
from api.permissions import IsAuthenticatedWithAdminFullAccess, has_full_access
from contact.models import Contact
from contact.serialisers import ContactSerializer

class ContactModelViewSet(ModelViewSet):
    serializer_class = ContactSerializer
    permission_classes = [IsAuthenticatedWithAdminFullAccess]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "email", "message", "user__email"]
    ordering_fields = ["created_at", "updated_at", "name", "email", "is_read"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = Contact.objects.select_related("user")
        if has_full_access(self.request.user):
            return queryset
        return queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
