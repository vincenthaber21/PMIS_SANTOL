"""URL patterns for borrowing app."""
from django.urls import path
from . import views

app_name = 'borrowing'

urlpatterns = [
    path('', views.borrow_list, name='list'),
    path('create/', views.borrow_create, name='create'),
    path('<int:pk>/', views.borrow_detail, name='detail'),
    path('<int:pk>/return/', views.borrow_return, name='return'),
]
