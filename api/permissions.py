from rest_framework.permissions import BasePermission


def has_full_access(user):
    return bool(
        user
        and user.is_authenticated
        and user.is_staff
        and user.is_superuser
    )


class IsAuthenticatedWithAdminFullAccess(BasePermission):
    """
    Require authentication for everyone.
    Staff superusers are treated as full-access users by the viewsets.
    """

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)
