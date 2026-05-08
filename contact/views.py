from rest_framework.viewsets import ModelViewSet
from contact.models import Contact
from contact.serialisers import ContactSerializer
from .permissions import IsAdminOrCreateOnly

class ContactModelViewSet(ModelViewSet):
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    permission_classes = [IsAdminOrCreateOnly]

    def perform_create(self, serializer):
        if self.request.user.is_authenticated:
            serializer.save(user=self.request.user)
        else:
            serializer.save()