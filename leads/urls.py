from django.urls import path
from .views import LeadListView, KommoWebhookView, TestFlowView, CallAnsweredWebhookView

urlpatterns = [
    path('leads/', LeadListView.as_view(), name='lead-list'),
    path('webhook/kommo/', KommoWebhookView.as_view(), name='kommo-webhook'),
    path('test-flow/', TestFlowView.as_view(), name='test-flow'),
    path('call-answered/', CallAnsweredWebhookView.as_view(), name='call-answered'),
]