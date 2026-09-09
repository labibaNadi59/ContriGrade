from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .forms import SignUpForm


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