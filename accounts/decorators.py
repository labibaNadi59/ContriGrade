import logging
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


def role_required(allowed_roles):
    """
    Restricts view access to specific user roles.
    Raises PermissionDenied (403) and logs unauthorized access attempts.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            if request.user.role not in allowed_roles:
                logger.warning(
                    f"Unauthorized access attempt by user_id={request.user.pk} "
                    f"with role={request.user.role} on path={request.path}"
                )
                raise PermissionDenied("You do not have permission to view this resource.")

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


# Convenience shortcuts
student_required = role_required(['STUDENT'])
instructor_required = role_required(['INSTRUCTOR', 'COORDINATOR'])
coordinator_required = role_required(['COORDINATOR'])