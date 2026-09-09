from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from accounts.decorators import student_required
from .models import Project, Team, TeamMember
from .forms import ProjectForm, TeamForm
from django.shortcuts import get_object_or_404
from accounts.models import User


@login_required
def dashboard_redirect(request):
    # Route System Admin to their specific dashboard
    if request.user.is_admin:
        return redirect('system_admin_dashboard')
    elif request.user.is_student:
        return redirect('student_dashboard')

    # For Instructors and Course Coordinators:
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('dashboard_redirect')
    else:
        form = ProjectForm()

    projects = Project.objects.all().order_by('-deadline')

    context = {
        'form': form,
        'projects': projects,
        'user': request.user
    }
    return render(request, 'academic/instructor_dashboard.html', context)


@student_required
def student_dashboard(request):

    membership = TeamMember.objects.filter(user=request.user).select_related('team__project').first()

    teammates = None
    if membership:

        teammates = membership.team.members.exclude(user_id=request.user.user_id)

    context = {
        'user': request.user,
        'membership': membership,
        'teammates': teammates
    }
    return render(request, 'academic/student_dashboard.html', context)



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

def team_edit(request, team_id):

    team = get_object_or_404(Team, team_id=team_id)
    error_message = None

    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            team = form.save()
            selected_students = form.cleaned_data['members']

            current_memberships = TeamMember.objects.filter(team=team)
            current_student_ids = set(current_memberships.values_list('user_id', flat=True))
            selected_student_ids = set(student.user_id for student in selected_students)

            TeamMember.objects.filter(team=team, user_id__in=current_student_ids - selected_student_ids).delete()

            for student_id in selected_student_ids - current_student_ids:
                student = User.objects.get(user_id=student_id)
                try:
                    tm = TeamMember(team=team, user=student)
                    tm.full_clean()
                    tm.save()
                except ValidationError as e:
                    error_message = f"Warning: {student.name} is already assigned to another team for this project."

            if not error_message:
                return redirect('team_management')
    else:
        form = TeamForm(instance=team)

    context = {
        'form': form,
        'team': team,
        'user': request.user,
        'error_message': error_message
    }
    return render(request, 'academic/team_edit.html', context)