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
    path('store/api/checkout/', views.store_checkout, name='store_checkout'),
    path('store/api/orders/', views.store_orders_list, name='store_orders_list'),
    path('store/api/wallet/', views.store_wallet_get, name='store_wallet_get'),
    path('store/api/contact/', views.store_contact, name='store_contact'),

    path('store/dashboard/', views.dashboard_home, name='dashboard_home'),
    path('store/dashboard/signups/', views.dashboard_signups, name='dashboard_signups'),
    path('store/dashboard/contacts/', views.dashboard_contacts, name='dashboard_contacts'),
    path('store/dashboard/contacts/<int:pk>/delete/', views.dashboard_contact_delete, name='dashboard_contact_delete'),
    path('store/dashboard/categories/', views.dashboard_categories, name='dashboard_categories'),
    path('store/dashboard/categories/add/', views.dashboard_category_add, name='dashboard_category_add'),
    path('store/dashboard/categories/<int:pk>/edit/', views.dashboard_category_edit, name='dashboard_category_edit'),
    path('store/dashboard/categories/<int:pk>/delete/', views.dashboard_category_delete, name='dashboard_category_delete'),
    path('store/dashboard/orders/', views.dashboard_orders, name='dashboard_orders'),
    path('store/dashboard/orders/<int:pk>/status/', views.dashboard_order_status_update, name='dashboard_order_status_update'),
    path('store/dashboard/logout/', views.dashboard_logout, name='dashboard_logout'),

    path('contact/', views.contact_lead, name='contact_lead'),
]
