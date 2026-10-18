from django.urls import path

from . import support_chat

# The support chat ("Chats") — its own product, mounted at /chats/ in
# edutrellis/urls.py. Separate accounts from the store/AI login (ChatUser).
urlpatterns = [
    path('', support_chat.chats_page, name='chats_page'),
    path('reset/<str:token>/', support_chat.reset_page, name='chats_reset'),
    path('api/signup/', support_chat.api_signup, name='chats_signup'),
    path('api/login/', support_chat.api_login, name='chats_login'),
    path('api/logout/', support_chat.api_logout, name='chats_logout'),
    path('api/forgot/', support_chat.api_forgot, name='chats_forgot'),
    path('api/username/', support_chat.api_username_check, name='chats_username_check'),
    path('api/messages/', support_chat.api_messages, name='chats_messages'),
    path('api/upload/', support_chat.api_upload, name='chats_upload'),
    path('api/location/', support_chat.api_location, name='chats_location'),
    path('api/call/', support_chat.api_call, name='chats_call'),
    path('file/<int:pk>/', support_chat.attachment, name='chats_attachment'),
    path('api/profile/', support_chat.api_profile, name='chats_profile'),
    path('api/guest/', support_chat.api_guest, name='chats_guest'),
    path('user-photo/<int:pk>/', support_chat.user_photo, name='chats_user_photo'),
    path('support-photo/', support_chat.support_photo, name='chats_support_photo'),
]
