from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import SignUpForm , AdminUserCreationForm, AdminUserUpdateForm
from django.db.models import Q
from .models import User



def signup_view(request):
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            form.save()
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







