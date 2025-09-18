from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('', views.dashboard, name='dashboard'),

    path('clients/', views.clients_list, name='clients_list'),
    path('clients/new/', views.client_create, name='clients_create'),
    path('clients/<int:pk>/', views.client_detail, name='clients_detail'),
    path('clients/<int:pk>/edit/', views.client_update, name='clients_update'),

    path('clients/<int:client_pk>/invoices/new/', views.invoice_create, name='invoice_create'),
    path('invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('invoices/<int:pk>/edit/', views.invoice_update, name='invoice_update'),
    path('invoices/<int:pk>/pdf/', views.invoice_pdf, name='invoice_pdf'),
]


