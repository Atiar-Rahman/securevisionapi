from rest_framework import serializers
from cameras.models import Camera

class CameraSerializer(serializers.ModelSerializer):
    class Meta:
        model = Camera
        fields = [
            "id",
            "name",
            "location",
            "camera_type",
            "stream_url",
            "is_active",
            "ai_enabled",
            "fps",
            "resolution",
            "status",
            "last_seen",
            "snapshot",       # AI-only field
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["last_seen", "snapshot", "created_at", "updated_at"]

    def validate_name(self, value):
        user = self.context['request'].user
        queryset = Camera.objects.filter(user=user, name=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("You already have a camera with this name.")
        return value
    
    
