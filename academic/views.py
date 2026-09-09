from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Project ,Team, TeamMember
from .forms import ProjectForm , TeamForm


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


def team_management(request):
    error_message = None

    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            # Save the team first
            team = form.save()
            selected_students = form.cleaned_data['members']

            # Now assign the students one by one so our validation rule runs
            for student in selected_students:
                try:
                    tm = TeamMember(team=team, user=student)
                    tm.full_clean()  # This triggers the "one team per project" rule
                    tm.save()
                except ValidationError as e:
                    error_message = f"Warning: {e.message}"

            if not error_message:
                return redirect('team_management')
    else:
        form = TeamForm()

    # Fetch all teams to display on the page
    teams = Team.objects.all().select_related('project')

    context = {
        'form': form,
        'teams': teams,
        'user': request.user,
        'error_message': error_message
    }
    return render(request, 'academic/team_management.html', context)