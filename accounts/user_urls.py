"""URL patterns for user management."""
from django.urls import path
from accounts import views

app_name = 'users'

urlpatterns = [
    path('', views.user_list, name='user_list'),
    path('create/', views.user_create, name='user_create'),
    path('create/send-otp/', views.user_create_send_otp, name='user_create_send_otp'),
    path('create/resend-otp/', views.user_create_resend_otp, name='user_create_resend_otp'),
    path('create/verify/', views.user_create_verify, name='user_create_verify'),
    path('<int:pk>/edit/', views.user_edit, name='user_edit'),
    path('<int:pk>/delete/', views.user_delete, name='user_delete'),
]
