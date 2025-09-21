from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('', views.dashboard, name='dashboard'),

    path('google/connect/', views.google_connect, name='google_connect'),
    path('google/callback/', views.google_callback, name='google_callback'),
    path('google/disconnect/', views.google_disconnect, name='google_disconnect'),
    path('google/drive/select/', views.google_drive_select, name='google_drive_select'),

    path('clients/', views.clients_list, name='clients_list'),
    path('clients/new/', views.client_create, name='clients_create'),
    path('clients/<int:pk>/', views.client_detail, name='clients_detail'),
    path('clients/<int:pk>/edit/', views.client_update, name='clients_update'),

    path('clients/<int:client_pk>/invoices/new/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/edit/', views.invoice_update, name='invoice_update'),
    path('invoices/<int:pk>/delete/', views.invoice_delete, name='invoice_delete'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('invoices/<int:pk>/send-email/', views.invoice_send_email, name='invoice_send_email'),
]


