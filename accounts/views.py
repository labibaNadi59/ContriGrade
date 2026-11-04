from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from academic.utils import validate_github_connection
from .forms import SignUpForm, AdminUserCreationForm, AdminUserUpdateForm, ProfileUpdateForm
from django.db.models import Q
from .models import User


@login_required
def profile_settings(request):
    if request.method == 'POST':
        # Action 1: Handle Profile Picture Deletion
        if 'remove_picture' in request.POST:
            if request.user.profile_picture:
                request.user.profile_picture.delete(save=False)  # Deletes the file from storage
                request.user.profile_picture = None
                request.user.save()
                messages.success(request, "Profile picture removed successfully.")

            # Redirect to the correct dashboard based on role
            role = request.user.role
            if role == 'STUDENT':
                return redirect('student_dashboard')
            elif role == 'INSTRUCTOR':
                return redirect('dashboard_redirect')
            elif role == 'COORDINATOR':
                return redirect('coordinator_dashboard')
            elif role == 'ADMIN':
                return redirect('system_admin_dashboard')
            else:
                return redirect('profile_settings')

        # Action 2: Handle Profile Update
        form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Your profile settings have been updated successfully.")

            # Redirect to the correct dashboard based on role
            role = request.user.role
            if role == 'STUDENT':
                return redirect('student_dashboard')
            elif role == 'INSTRUCTOR':
                return redirect('dashboard_redirect')
            elif role == 'COORDINATOR':
                return redirect('coordinator_dashboard')
            elif role == 'ADMIN':
                return redirect('system_admin_dashboard')
            else:
                return redirect('profile_settings')
    else:
        form = ProfileUpdateForm(instance=request.user)

    return render(request, 'accounts/profile_settings.html', {'form': form})


def signup_view(request):
    # Prevent logged-in users from accessing the signup page
    if request.user.is_authenticated:
        role = request.user.role
        if role == 'STUDENT':
            return redirect('student_dashboard')
        elif role == 'INSTRUCTOR':
            return redirect('dashboard_redirect')
        elif role == 'COORDINATOR':
            return redirect('coordinator_dashboard')
        elif role == 'ADMIN':
            return redirect('system_admin_dashboard')

    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            # Save the new user to the database
            user = form.save()

            # Instantly establish the session
            login(request, user)

            # Route directly to their specific dashboard
            role = user.role
            if role == 'STUDENT':
                return redirect('student_dashboard')
            elif role == 'INSTRUCTOR':
                return redirect('dashboard_redirect')
            elif role == 'COORDINATOR':
                return redirect('coordinator_dashboard')
            elif role == 'ADMIN':
                return redirect('system_admin_dashboard')
            else:
                return redirect('login')
    else:
        form = SignUpForm()

    return render(request, 'accounts/signup.html', context={'form': form})

@login_required
def system_admin_dashboard(request):
    if not request.user.is_admin:
        return redirect('dashboard_redirect')

    context = {
        'user': request.user
    }
    return render(request, 'accounts/system_admin_dashboard.html', context)

@login_required
def admin_user_management(request):
    if not request.user.is_admin:
        return redirect('dashboard_redirect')

    query = request.GET.get('q', '')
    role_filter = request.GET.get('role', '')

    users = User.objects.all().order_by('-created_at')

    if query:
        users = users.filter(Q(name__icontains=query) | Q(email__icontains=query))
    if role_filter:
        users = users.filter(role=role_filter)

    context = {
        'users': users,
        'query': query,
        'role_filter': role_filter,
        'roles': User.Role.choices,
    }
    return render(request, 'accounts/admin_user_management.html', context)


@login_required
def admin_user_create(request):
    if not request.user.is_admin:
        return redirect('dashboard_redirect')

    if request.method == 'POST':
        form = AdminUserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('admin_user_management')
    else:
        form = AdminUserCreationForm()

    return render(request, 'accounts/admin_user_form.html', {'form': form, 'action': 'Create'})


@login_required
def admin_user_update(request, user_id):
    if not request.user.is_admin:
        return redirect('dashboard_redirect')

    target_user = get_object_or_404(User, user_id=user_id)

    if request.method == 'POST':
        form = AdminUserUpdateForm(request.POST, instance=target_user)
        if form.is_valid():
            form.save()
            return redirect('admin_user_management')
    else:
        form = AdminUserUpdateForm(instance=target_user)

    return render(request, 'accounts/admin_user_form.html', {'form': form, 'action': 'Update'})


@login_required
def admin_user_toggle_status(request, user_id):
    if not request.user.is_admin:
        return redirect('dashboard_redirect')

    target_user = get_object_or_404(User, user_id=user_id)
    # Prevent admin from deactivating themselves
    if target_user != request.user:
        target_user.is_active = not target_user.is_active
        target_user.save()

    return redirect('admin_user_management')


@login_required
def system_api_settings(request):
    # Ensure only admins can access this
    if request.user.role != 'ADMIN':
        return redirect('login')

    connection_status = None

    # If the admin clicks the "Test Connection" button
    if request.method == 'POST' and 'test_connection' in request.POST:
        connection_status = validate_github_connection()

    return render(request, 'accounts/api_settings.html', {
        'token_configured': bool(settings.GITHUB_API_TOKEN),
        'connection_status': connection_status,
    })



