from reviews.models import Reviews
from rest_framework import serializers


class ReviewSerializer(serializers.ModelSerializer):

    class Meta:
        model = Reviews
        fields = ['id','user','title','rating','comments','created_at','updated_at']
        read_only_fields = ['id','user','created_at','updated_at']

        
