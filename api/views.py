import os
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework import status
from datetime import datetime
from detection.ml.pridict_gray import is_model_loaded as is_main_model_loaded, warmup_model as warmup_main_model
from detection.ml.predict3dcnn import is_model_loaded as is_3d_model_loaded, warmup_model as warmup_3d_model

@api_view(['GET','HEAD'])
@permission_classes([AllowAny])
def Home(request):
    return Response({
        "status": "success",
        "message": "SecureVisionAI Model Running",
        "timestamp": datetime.now(),
        "user": str(request.user) if request.user.is_authenticated else "anonymous"
    }, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def warmup_models(request):
    expected_token = os.getenv("MODEL_WARMUP_TOKEN", "").strip()
    provided_token = request.headers.get("X-Warmup-Token", "").strip()

    if expected_token and provided_token != expected_token:
        return Response({"error": "Invalid warmup token"}, status=status.HTTP_403_FORBIDDEN)

    main_was_loaded = is_main_model_loaded()
    model_3d_was_loaded = is_3d_model_loaded()

    include_3d = str(
        request.query_params.get("include_3d", "false")
    ).strip().lower() in {"1", "true", "yes"}

    warmup_main_model()
    if include_3d:
        warmup_3d_model()

    return Response(
        {
            "status": "success",
            "message": "Models warmed up",
            "main_model_loaded_before": main_was_loaded,
            "model_3d_loaded_before": model_3d_was_loaded,
            "main_model_loaded_now": True,
            "model_3d_loaded_now": include_3d or model_3d_was_loaded,
            "include_3d": include_3d,
            "timestamp": datetime.now(),
        },
        status=status.HTTP_200_OK,
    )
