from django.urls import path
from myapp import views

urlpatterns = [
    path('', views.home, name='home'),
    path('websitecreation/', views.home2, name='home2'),
    path('store/', views.estore, name='estore'),
    path('store/api/signup/', views.store_signup, name='store_signup'),
    path('store/api/login/', views.store_login, name='store_login'),
    path('store/api/logout/', views.store_logout, name='store_logout'),
    path('store/api/profile/update/', views.store_profile_update, name='store_profile_update'),
    path('store/api/profile/password/', views.store_password_change, name='store_password_change'),
    path('store/api/cart/', views.store_cart_get, name='store_cart_get'),
    path('store/api/cart/add/', views.store_cart_add, name='store_cart_add'),
    path('store/api/cart/update/', views.store_cart_update, name='store_cart_update'),
    path('store/api/cart/remove/', views.store_cart_remove, name='store_cart_remove'),
    path('store/api/contact/', views.store_contact, name='store_contact'),
    path('contact/', views.contact_lead, name='contact_lead'),
]
