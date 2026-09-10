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
]