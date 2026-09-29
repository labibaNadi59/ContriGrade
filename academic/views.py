from django.contrib import messages
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required
from accounts.decorators import student_required
from .models import Project, Team, TeamMember, Course, CourseSection
from .forms import ProjectForm, TeamForm, AssignInstructorForm, CourseSectionForm, CourseForm, StudentProjectRoleForm, \
    StudentEnrollmentForm, TeamRepoForm
from django.shortcuts import get_object_or_404
from accounts.models import User
from .utils import fetch_team_commits, analyze_team_contributions


@login_required
def project_master_report(request, project_id):
    if request.user.role not in ['INSTRUCTOR', 'ADMIN', 'COORDINATOR']:
        messages.error(request, "Access denied. Instructor privileges required.")
        return redirect('student_dashboard')

    if request.user.role in ['ADMIN', 'COORDINATOR']:
        project = get_object_or_404(Project, pk=project_id)
    else:
        project = get_object_or_404(Project, pk=project_id, section__instructor=request.user)

    teams = project.teams.all()

    master_data = []
    project_total_commits = 0
    teams_with_repos = 0

    # Aggregate data from all teams
    for team in teams:
        if team.github_repo_url:
            teams_with_repos += 1
            fetch_result = fetch_team_commits(team)

            if fetch_result['status'] == 'success':
                analytics = analyze_team_contributions(team, fetch_result['commits'])
                project_total_commits += analytics['total_commits']

                for pk, student in analytics['mapped_students'].items():
                    master_data.append({
                        'name': student['name'],
                        'team_name': team.team_name,
                        'github_username': student['github_username'],
                        'role': student['role'],
                        'commit_count': student['commit_count'],
                        'total_additions': student.get('total_additions', 0),
                        'total_deletions': student.get('total_deletions', 0),
                        'flags': student.get('flags', [])
                    })

    # Sort students by highest commit count by default
    master_data.sort(key=lambda x: x['commit_count'], reverse=True)

    return render(request, 'academic/master_report.html', {
        'project': project,
        'master_data': master_data,
        'total_teams': teams.count(),
        'teams_with_repos': teams_with_repos,
        'project_total_commits': project_total_commits
    })


@login_required
def reports_hub(request):
    if request.user.role not in ['INSTRUCTOR', 'ADMIN', 'COORDINATOR']:
        messages.error(request, "Access denied.")
        return redirect('student_dashboard')

    if request.user.role in ['ADMIN', 'COORDINATOR']:
        projects = Project.objects.all()
    else:
        #  Jump through the 'section' to check the instructor
        projects = Project.objects.filter(section__instructor=request.user)

    return render(request, 'academic/reports_hub.html', {
        'projects': projects
    })

@login_required
def team_analytics_dashboard(request, team_id):
    # Security: Ensure only instructors or admins can access this page
    if request.user.role not in ['INSTRUCTOR', 'ADMIN', 'COORDINATOR']:
        messages.error(request, "Access denied. Instructor privileges required.")
        return redirect('student_dashboard')

    team = get_object_or_404(Team, pk=team_id)
    analytics_data = None
    error_message = None

    recent_commits = []
    if not team.github_repo_url:
        error_message = "This team has not linked a GitHub repository yet."
    else:
        # 1. Fetch raw commits
        fetch_result = fetch_team_commits(team)

        if fetch_result['status'] == 'success':
            recent_commits = fetch_result['commits'][:15]
            # 2. Map commits to students
            analytics_data = analyze_team_contributions(team, fetch_result['commits'])

            # 3. Calculate percentages for the UI charts
            total = analytics_data['total_commits']
            if total > 0:
                for pk, student in analytics_data['mapped_students'].items():
                    student['percentage'] = round((student['commit_count'] / total) * 100, 1)
            else:
                for pk, student in analytics_data['mapped_students'].items():
                    student['percentage'] = 0.0
        else:
            error_message = fetch_result.get('message', 'Failed to fetch commits from GitHub.')

    return render(request, 'academic/team_analytics.html', {
        'team': team,
        'analytics': analytics_data,
        'recent_commits': recent_commits,  # NEW
        'error_message': error_message
    })


@login_required
@student_required
def update_team_repo(request, team_id):
    # 1. Security check: Get the team, and verify the current user is a member!
    team = get_object_or_404(Team, pk=team_id)
    is_member = TeamMember.objects.filter(team=team, user=request.user).exists()

    if not is_member:
        messages.error(request, "Security block: You can only link repositories for your own team.")
        return redirect('student_dashboard')

    if request.method == 'POST':
        form = TeamRepoForm(request.POST, instance=team)
        if form.is_valid():
            form.save()
            messages.success(request, f"Successfully linked GitHub repository for team '{team.team_name}'.")
            return redirect('student_dashboard')
    else:
        form = TeamRepoForm(instance=team)

    return render(request, 'academic/update_team_repo.html', {
        'form': form,
        'team': team
    })

@login_required
def dashboard_redirect(request):
    if request.user.is_admin:
        return redirect('system_admin_dashboard')
    elif request.user.is_student:
        return redirect('student_dashboard')
    elif request.user.is_coordinator:
        return redirect('coordinator_dashboard')

    # Strictly for Instructors:
    if request.method == 'POST':
        # Pass request.user into the form initialization
        form = ProjectForm(request.POST, user=request.user)
        if form.is_valid():
            project = form.save(commit=False)

            # Security Check: Double-check that this instructor is assigned to the section
            if project.section.instructor == request.user:
                project.save()
                return redirect('dashboard_redirect')
            else:
                form.add_error('section', 'You are not authorized to create a project for a section you do not teach.')
    else:
        # Pass request.user here too so the GET form filters properly
        form = ProjectForm(user=request.user)

    # Instructors should only see projects belonging to their assigned sections
    projects = Project.objects.filter(section__instructor=request.user).order_by('-deadline')

    context = {
        'form': form,
        'projects': projects,
        'user': request.user
    }
    return render(request, 'academic/instructor_dashboard.html', context)




@login_required
@student_required
def student_dashboard(request):
    # Assessment Hub
    memberships = TeamMember.objects.filter(user=request.user).select_related(
        'team__project__section__course'
    )
    return render(request, 'academic/student_dashboard.html', {
        'user': request.user,
        'memberships': memberships,
    })


@login_required
@student_required
def student_courses(request):
    # My Enrolled Courses
    my_sections = CourseSection.objects.filter(students=request.user).select_related('course', 'instructor')


    enroll_form = StudentEnrollmentForm(user=request.user)

    return render(request, 'academic/student_courses.html', {
        'my_sections': my_sections,
        'enroll_form': enroll_form,
    })


@login_required
@student_required
def enroll_in_section(request):
    # Process enrollment and redirect back to the Courses page
    if request.method == 'POST':
        form = StudentEnrollmentForm(request.POST, user=request.user)
        if form.is_valid():
            section = form.cleaned_data['section']

            section.students.add(request.user)
            messages.success(request,
                             f"Successfully enrolled in {section.course.course_code} - {section.section_name}.")

    return redirect('student_courses')

@login_required
def team_management(request):
    error_message = None

    # Restrict teams query based on user role
    if request.user.role == 'INSTRUCTOR':
        teams = Team.objects.filter(project__section__instructor=request.user).select_related('project')
    else:
        teams = Team.objects.all().select_related('project')

    if request.method == 'POST':
        # Pass user=request.user so the form restricts projects to assigned sections
        form = TeamForm(request.POST, user=request.user)
        if form.is_valid():
            team = form.save()
            selected_students = form.cleaned_data.get('members', [])

            # Assign students safely using get_or_create and running validation
            for student in selected_students:
                try:
                    tm, created = TeamMember.objects.get_or_create(team=team, user=student)
                    tm.full_clean()
                    tm.save()
                except ValidationError as e:
                    # Safely handle validation error messages
                    err_msg = e.messages[0] if hasattr(e, 'messages') else str(e)
                    error_message = f"Warning: {err_msg}"

            if not error_message:
                return redirect('team_management')
        else:
            # Prints form errors to your PyCharm terminal if validation fails
            print("TeamForm Errors:", form.errors)
    else:
        # Pass user=request.user for GET requests too
        form = TeamForm(user=request.user)

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


@login_required
def coordinator_dashboard(request):
    if not request.user.is_coordinator:
        return redirect('dashboard_redirect')

    courses = Course.objects.all().select_related('coordinator')
    sections = CourseSection.objects.all().select_related('course', 'instructor')
    instructors = User.objects.filter(role='INSTRUCTOR')
    section_form = CourseSectionForm()

    context = {
        'user': request.user,
        'courses': courses,
        'sections': sections,
        'instructors': instructors,
        'section_form': section_form,
    }
    return render(request, 'academic/coordinator_dashboard.html', context)

@login_required
def section_create(request):
    if not request.user.is_coordinator:
        return redirect('dashboard_redirect')

    if request.method == 'POST':
        form = CourseSectionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('coordinator_dashboard')
    else:
        form = CourseSectionForm()

    return render(request, 'academic/section_form.html', {'form': form})


@login_required
def section_update_instructor(request, section_id):
    if not request.user.is_coordinator:
        return redirect('dashboard_redirect')

    section = get_object_or_404(CourseSection, section_id=section_id)

    if request.method == 'POST':
        instructor_id = request.POST.get('instructor')

        if instructor_id:
            # Assign the selected instructor using user_id from your User model
            instructor = User.objects.filter(user_id=instructor_id, role='INSTRUCTOR').first()
            section.instructor = instructor
        else:
            # Clear the instructor safely now that null=True is allowed
            section.instructor = None

        section.save()

    return redirect('coordinator_dashboard')


@login_required
def section_delete(request, section_id):
    if not request.user.is_coordinator:
        return redirect('dashboard_redirect')

    section = get_object_or_404(CourseSection, section_id=section_id)
    if request.method == 'POST':
        section.delete()

    return redirect('coordinator_dashboard')


@login_required
def course_create(request):
    if not request.user.is_coordinator:
        return redirect('dashboard_redirect')

    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('coordinator_dashboard')
    else:
        form = CourseForm()
        # Optionally pre-fill the coordinator field with the current user if they are a coordinator
        if request.user.is_coordinator:
            form.initial['coordinator'] = request.user

    return render(request, 'academic/course_form.html', {'form': form})


@login_required
def update_student_project_role(request, membership_id):
    # Strict ownership check: student can only edit their own role
    membership = get_object_or_404(TeamMember, pk=membership_id, user=request.user)

    if request.method == 'POST':
        form = StudentProjectRoleForm(request.POST, instance=membership)
        if form.is_valid():
            form.save()
            messages.success(request, f"Updated role and responsibilities for {membership.team.project.title}.")
            return redirect('student_dashboard')
    else:
        form = StudentProjectRoleForm(instance=membership)

    return render(request, 'academic/update_student_project_role.html', {
        'form': form,
        'membership': membership,
    })
