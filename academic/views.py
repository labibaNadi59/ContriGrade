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
import csv
from django.http import HttpResponse
from django.http import JsonResponse


@login_required
def load_project_students(request):
    project_id = request.GET.get('project_id')
    student_list = []

    if project_id:
        try:
            # 1. Find the project
            project = Project.objects.get(pk=project_id)
            # 2. Get the students enrolled in this project's section
            students = project.section.students.all().order_by('name')

            # 3. Format it for the frontend
            for student in students:
                student_list.append({
                    'id': student.pk,
                    'name': student.name or student.username
                })
        except Project.DoesNotExist:
            pass

    return JsonResponse({'students': student_list})

@login_required
@student_required
def student_dashboard(request):
    # This view now serves as "My Projects"
    memberships = TeamMember.objects.filter(user=request.user).select_related('team__project')

    return render(request, 'academic/student_dashboard.html', {
        'memberships': memberships
    })


@login_required
@student_required
def student_team_progress(request, team_id):
    # Securely fetch only the team this student belongs to
    team = get_object_or_404(Team, pk=team_id, members=request.user)

    recent_commits = []
    error_message = None
    analytics_data = None
    force_refresh = request.GET.get('refresh') == 'true'

    if not team.github_repo_url:
        error_message = "Your team has not linked a GitHub repository yet."
    else:
        fetch_result = fetch_team_commits(team, force_refresh=force_refresh)
        if fetch_result['status'] == 'success':
            recent_commits = fetch_result['commits'][:15]
            analytics_data = analyze_team_contributions(team, fetch_result['commits'])
            analytics_data['total_branches'] = fetch_result.get('total_branches', 1)
        else:
            error_message = fetch_result.get('message', 'Failed to fetch commits from GitHub.')

    return render(request, 'academic/student_progress.html', {
        'team': team,
        'analytics': analytics_data,
        'recent_commits': recent_commits,
        'error_message': error_message
    })



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

    # Check if the user clicked the refresh button
    force_refresh = request.GET.get('refresh') == 'true'
    # Aggregate data from all teams
    for team in teams:
        if team.github_repo_url:
            teams_with_repos += 1
            fetch_result = fetch_team_commits(team, force_refresh=force_refresh)

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

    # Intercept the request and generate a CSV if requested ---
    if request.GET.get('export') == 'csv':
        # Tell the browser this is a CSV file download
        response = HttpResponse(content_type='text/csv')

        # Clean the project title to make a nice filename (e.g., "Web_Dev_101_Grades.csv")
        safe_title = project.title.replace(' ', '_').replace('/', '-')
        response['Content-Disposition'] = f'attachment; filename="{safe_title}_Report.csv"'

        writer = csv.writer(response)

        # Write the Header Row
        writer.writerow(['Student Name', 'GitHub Username', 'Team', 'Role', 'Commits', 'Lines Added', 'Lines Deleted',
                         'Integrity Flags'])

        # Write the Data Rows
        for student in master_data:
            # Combine the orange flags into a single readable string, or write 'Clean'
            flags_str = " | ".join(student.get('flags', [])) if student.get('flags') else "Clean"

            writer.writerow([
                student['name'],
                student['github_username'] or 'No GitHub ID',
                student['team_name'],
                student['role'] or 'Unassigned',
                student['commit_count'],
                student.get('total_additions', 0),
                student.get('total_deletions', 0),
                flags_str
            ])

        return response
    # -----------------------------------------------------------------
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
    # Check if the user clicked the refresh button
    force_refresh = request.GET.get('refresh') == 'true'

    if not team.github_repo_url:
        error_message = "This team has not linked a GitHub repository yet."
    else:
        # 1. Pass the force_refresh flag to the fetcher
        fetch_result = fetch_team_commits(team, force_refresh=force_refresh)

        if fetch_result['status'] == 'success':
            recent_commits = fetch_result['commits']

            # 2. Map commits to students (calculates the correct Impact percentage )
            analytics_data = analyze_team_contributions(team, fetch_result['commits'])
            analytics_data['total_branches'] = fetch_result.get('total_branches', 1)

        else:
            error_message = fetch_result.get('message', 'Failed to fetch commits from GitHub.')

    return render(request, 'academic/team_analytics.html', {
        'team': team,
        'analytics': analytics_data,
        'recent_commits': recent_commits,
        'error_message': error_message
    })


@login_required
@student_required
def update_team_repo(request, team_id):
    team = get_object_or_404(Team, pk=team_id)
    is_member = TeamMember.objects.filter(team=team, user=request.user).exists()

    if not is_member:
        messages.error(request, "Security block: You can only link repositories for your own team.")
        return redirect('student_dashboard')

    # -STRICT DEADLINE ENFORCEMENT ---
    if not team.project.is_active():
        messages.error(request, f"Submission locked. The deadline for {team.project.title} has passed.")
        return redirect('student_dashboard')
    # ----------------------------------------

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

    # STRICT DEADLINE ENFORCEMENT ---
    if not membership.team.project.is_active():
        messages.error(request, f"Role updates locked. The deadline for {membership.team.project.title} has passed.")
        return redirect('student_dashboard')
    # ----------------------------------------

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

@login_required
def edit_project(request, project_id):
    # Security: Ensure only instructors or coordinators access this
    if request.user.role not in ['INSTRUCTOR', 'COORDINATOR']:
        messages.error(request, "Access denied.")
        return redirect('dashboard_redirect')

    project = get_object_or_404(Project, pk=project_id)

    # Security: Ensure the instructor actually owns this project's section
    if request.user.role == 'INSTRUCTOR' and project.section.instructor != request.user:
        messages.error(request, "You can only edit projects assigned to your sections.")
        return redirect('dashboard_redirect')

    if request.method == 'POST':
        # Pass both request.POST and the existing project instance
        form = ProjectForm(request.POST, instance=project, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, f"Successfully updated '{project.title}'.")
            return redirect('dashboard_redirect')
    else:
        # Pre-fill the form with existing data
        form = ProjectForm(instance=project, user=request.user)

    return render(request, 'academic/edit_project.html', {
        'form': form,
        'project': project
    })

