from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from alert.models import Alert
from alert.serializers import AlertSerializer

class AlertViewSet(ModelViewSet):
    serializer_class = AlertSerializer
    permission_classes = [IsAuthenticated]


    def get_queryset(self):
        return Alert.objects.filter(user = self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user = self.request.user)

