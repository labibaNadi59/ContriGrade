from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard_redirect, name='dashboard_redirect'),
    path('teams/', views.team_management, name='team_management'),
]