from rest_framework.permissions import BasePermission, SAFE_METHODS

class IsAdminOrCreateOnly(BasePermission):

    def has_permission(self, request, view):
        # Admin হলে সব allow
        if request.user and request.user.is_staff:
            return True

        # Non-admin হলে শুধু POST allow
        if request.method == "POST":
            return True

        return False