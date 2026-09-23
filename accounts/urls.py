from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
path('signup/', views.signup_view, name='signup'),
path('system/dashboard/', views.system_admin_dashboard, name='system_admin_dashboard'),
path('management/users/', views.admin_user_management, name='admin_user_management'),
    path('management/users/create/', views.admin_user_create, name='admin_user_create'),
    path('management/users/<int:user_id>/update/', views.admin_user_update, name='admin_user_update'),
    path('management/users/<int:user_id>/toggle/', views.admin_user_toggle_status, name='admin_user_toggle_status'),
]

