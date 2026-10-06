from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_redirect, name='dashboard_redirect'),
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
    path('coordinator/dashboard/', views.coordinator_dashboard, name='coordinator_dashboard'),
path('coordinator/courses/create/', views.course_create, name='course_create'),
path('coordinator/sections/create/', views.section_create, name='section_create'),
    path('coordinator/sections/<int:section_id>/assign/', views.section_update_instructor, name='section_update_instructor'),
    path('coordinator/sections/<int:section_id>/delete/', views.section_delete, name='section_delete'),
    path('teams/', views.team_management, name='team_management'),
    path('teams/<int:team_id>/edit/', views.team_edit, name='team_edit'),

path('student/', views.student_dashboard, name='student_dashboard'),
path('student/courses/', views.student_courses, name='student_courses'),
    path('student/enroll/', views.enroll_in_section, name='enroll_in_section'),
    path('student/memberships/<int:membership_id>/role/', views.update_student_project_role, name='update_student_project_role'),
path('student/team/<int:team_id>/repo/', views.update_team_repo, name='update_team_repo'),
path('instructor/team/<int:team_id>/analytics/', views.team_analytics_dashboard, name='team_analytics_dashboard'),
path('instructor/project/<int:project_id>/report/', views.project_master_report, name='project_master_report'),
path('instructor/reports/', views.reports_hub, name='reports_hub'),

path('student/team/<int:team_id>/progress/', views.student_team_progress, name='student_team_progress'),
path('ajax/load-project-students/', views.load_project_students, name='ajax_load_project_students'),

path('instructor/project/<int:project_id>/edit/', views.edit_project, name='edit_project'),
path('student/deliverable/<int:deliverable_id>/edit/', views.edit_deliverable, name='edit_deliverable'),
    path('student/deliverable/<int:deliverable_id>/delete/', views.delete_deliverable, name='delete_deliverable'),


]