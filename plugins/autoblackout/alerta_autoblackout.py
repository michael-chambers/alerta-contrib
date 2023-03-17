import logging
import os
import requests

from alerta.plugins import PluginBase, app

from alerta.models.alert import Alert

# set plugin logger
LOG = logging.getLogger('alerta.plugins.auto-blackout')

BASE_URL = app.config.get('BASE_URL') or os.environ.get('BASE_URL')
API_URL = f'http://localhost:8080{BASE_URL}'
API_KEY = os.environ.get('ALERTA_API_KEY')
BLACKOUT_EVENTS = app.config.get('AUTOBLACKOUT_EVENTS')

class AutoBlackout(PluginBase):
    def __init__(self, name=None):
        self.blackoutUrl=f'{API_URL}/blackout'
        self.blackoutHeaders={
            "Authorization": f"Key {API_KEY}",
            "Content-type": "application/json"
        }
        super(AutoBlackout, self).__init__(name)

    def pre_receive(self, alert, **kwargs):
        return alert
    
    def post_receive(self, alert, **kwargs):
        if alert is not None:
            if len(BLACKOUT_EVENTS) == 0:
                return alert
            for event in BLACKOUT_EVENTS:
                if str.upper(event) == str.upper(alert.event):
                    LOG.debug(f'blackout event {alert.event} identified for alert {alert.id}')
                    blackoutRequest = {
                        "environment": alert.environment
                    }
                    try:
                        requests.post(self.blackoutUrl, json=blackoutRequest, headers=self.blackoutHeaders)
                    except Exception:
                        LOG.error(f'Unable to complete POST API request to create blackout for alert {alert.id}')
        return alert

    def status_change(self, alert, status, text, **kwargs):
        return