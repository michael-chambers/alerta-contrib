import json
import logging
import os
import requests

from alerta.plugins import PluginBase, app

from alerta.models.alert import Alert

# set plugin logger
LOG = logging.getLogger('alerta.plugins.auto-blackout')

BASE_URL = app.config.get('BASE_URL') or os.environ.get('BASE_URL')
API_URL = f'http://localhost:8080{BASE_URL}'
API_KEY = os.environ.get('ALERTA_API_KEY') or os.environ.get('ADMIN_KEY')
BLACKOUT_EVENTS = app.config.get('AUTOBLACKOUT_EVENTS') or os.environ.get('AUTOBLACKOUT_EVENTS')

class AutoBlackout(PluginBase):
    def __init__(self, name=None):
        self.blackoutUrl=f'{API_URL}/blackout'
        if app.config.get('AUTH_REQUIRED'):
            self.blackoutHeaders={
                "Authorization": f"Key {API_KEY}",
                "Content-type": "application/json"
            }
        else:
            self.blackoutHeaders={
                "Content-type": "application/json"
            }
        super(AutoBlackout, self).__init__(name)

    def pre_receive(self, alert, **kwargs):
        if alert is not None:
            if 'blackout' in alert.attributes.keys():
                blackoutId = alert.attributes['blackout']
                LOG.debug(f'pre_receive reached for alert {alert.id} with attached blackout of {blackoutId}')

        return alert
    
    def post_receive(self, alert, **kwargs):
        if alert is not None:
            if BLACKOUT_EVENTS is None:
                LOG.error('No AUTOBLACKOUT_EVENTS defined, aborting autoblackout post_receive function')
                return alert
            for event in BLACKOUT_EVENTS:
                LOG.debug(f'comparing event against blackout event {event}')
                if str.upper(event) == str.upper(alert.event):
                    LOG.debug(f'blackout event {alert.event} identified for alert {alert.id}')
                    blackoutRequest = {
                        "environment": alert.environment
                    }
                    try:
                        response = requests.post(self.blackoutUrl, json=blackoutRequest, headers=self.blackoutHeaders)
                        response_data = json.loads(response.text)
                        blackoutId = response_data['blackout']['id']
                        LOG.debug(f'blackout created with ID {blackoutId}')
                        alert.attributes['blackout'] = blackoutId
                    except Exception:
                        LOG.error(f'Unable to complete POST API request to create blackout for alert {alert.id}')
        return alert

    def status_change(self, alert, status, text, **kwargs):
        return