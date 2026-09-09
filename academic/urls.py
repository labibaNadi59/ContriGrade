from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_redirect, name='dashboard_redirect'),
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
    path('teams/', views.team_management, name='team_management'),
    path('teams/<int:team_id>/edit/', views.team_edit, name='team_edit'),
]