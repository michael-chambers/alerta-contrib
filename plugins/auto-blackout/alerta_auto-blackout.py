import os
import requests

from alerta.plugins import PluginBase, app

API_URL = 'http://localhost:8080/api'
API_KEY = os.environ.get('ALERTA_API_KEY')
UPDATE_EVENT = "MCCClusterUpdating"

class AutoBlackout(PluginBase):
    def pre_receive(self, alert, **kwargs):
        # TODO
        return alert
    
    def post_receive(self, alert, **kwargs):
        if alert.event == "MCCClusterUpdating":
            blackoutRequest = {
                "environment": alert.environment,
                "event": UPDATE_EVENT
            }
            requests.post(f'{API_URL}/blackout', data=blackoutRequest, headers=f'Authorization: Key {API_KEY}')
        return alert