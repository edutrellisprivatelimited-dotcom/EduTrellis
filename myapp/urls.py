from django.urls import path
from myapp import views

urlpatterns = [
    path('', views.home, name='home'),
    path('websitecreation/', views.home2, name='home2'),
    path('store/', views.estore, name='estore'),
    path('contact/', views.contact_lead, name='contact_lead'),
]
