from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework import status
from datetime import datetime

@api_view(['GET','HEAD'])
@permission_classes([AllowAny])
def Home(request):
    return Response({
        "status": "success",
        "message": "SecureVisionAI Model Running",
        "timestamp": datetime.now(),
        "user": str(request.user) if request.user.is_authenticated else "anonymous"
    }, status=status.HTTP_200_OK)
