"""URL patterns for core app."""
from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('audit-trail/', views.audit_trail, name='audit_trail'),
    path('notifications/', views.notifications_view, name='notifications'),
    path('search/', views.global_search, name='search'),
]
