from django.urls import path
from myapp import views

urlpatterns = [
    path('', views.home, name='home'),
    path('contact/', views.contact_lead, name='contact_lead'),
]
