from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Project
from .forms import ProjectForm


@login_required
def dashboard_redirect(request):
    # Route the user based on their role
    if request.user.is_student:
        return HttpResponse("Student Dashboard coming soon!")

    # For Instructors, Coordinators, and Admins:
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dashboard_redirect')  # Refresh page after saving
    else:
        form = ProjectForm()

    # Fetch all active projects to display on the dashboard
    projects = Project.objects.all().order_by('-deadline')

    context = {
        'form': form,
        'projects': projects,
        'user': request.user
    }
    return render(request, 'academic/instructor_dashboard.html', context)