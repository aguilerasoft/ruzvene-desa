import json
from django.db.models.signals import post_save
from django.dispatch import receiver
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .models import Lead
from .serializers import LeadSerializer

@receiver(post_save, sender=Lead)
def broadcast_lead_update(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    # Serializar el lead (asumimos que existe LeadSerializer)
    serializer = LeadSerializer(instance)
    lead_data = serializer.data

    # Enviar al grupo 'leads_updates'
    async_to_sync(channel_layer.group_send)(
        'leads_updates',
        {
            'type': 'lead_update',
            'lead': lead_data
        }
    )
