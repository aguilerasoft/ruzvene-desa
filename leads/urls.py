from django.urls import path
from .views import LeadListView, KommoWebhookView

urlpatterns = [
    path('leads/', LeadListView.as_view(), name='lead-list'),
    path('webhook/kommo/', KommoWebhookView.as_view(), name='kommo-webhook'),
]