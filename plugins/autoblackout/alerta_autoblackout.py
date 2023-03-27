import json
import logging
import os
import requests

from alerta.plugins import PluginBase, app

LOG = logging.getLogger('alerta.plugins.autoblackout')

BASE_URL = app.config.get('BASE_URL') or os.environ.get('BASE_URL')
API_URL = f'http://localhost:8080{BASE_URL}'
API_KEY = os.environ.get('ALERTA_API_KEY') or os.environ.get('ADMIN_KEY')
BLACKOUT_EVENTS = app.config.get('AUTOBLACKOUT_EVENTS') or os.environ.get('AUTOBLACKOUT_EVENTS')
MGMT_CLUSTER_NAME = 'kaas-mgmt'


class AutoBlackout(PluginBase):
    def __init__(self, name=None):
        self.blackout_url = f'{API_URL}/blackout'
        self.get_blackouts_url = f'{API_URL}/blackouts'
        if app.config.get('AUTH_REQUIRED'):
            self.blackout_headers = {
                "Authorization": f"Key {API_KEY}",
                "Content-type": "application/json"
            }
            self.authorization_header = {
                "Authorization": f"Key {API_KEY}"
            }
        else:
            self.blackout_headers = {
                "Content-type": "application/json"
            }
        super(AutoBlackout, self).__init__(name)

    def _create_blackout(self, alert):
        blackout_duration = app.config.get(
            'AUTOBLACKOUT_MGMT_DURATION' if alert.resource == MGMT_CLUSTER_NAME else 'AUTOBLACKOUT_CHILD_DURATION'
        ) or app.config.get('BLACKOUT_DURATION')

        blackout_request = {
            "duration": blackout_duration,
            "environment": alert.environment,
            "resource": alert.resource,
            "text": alert.event,
        }
        try:
            # create the blackout
            requests.post(self.blackout_url, json=blackout_request, headers=self.blackout_headers)
            LOG.debug('Blackout created successfully')
        except Exception:
            LOG.error(f'Unable to complete POST API request to create blackout for alert {alert.id}')

    def _delete_blackout(self, alert):
        try:
            response = requests.get(self.get_blackouts_url, headers=self.authorization_header) if app.config.get('AUTH_REQUIRED') else requests.get(self.get_blackouts_url)
        except Exception:
            LOG.error('Unable to retrieve list of current blackouts')
            return

        blackout_data = json.loads(response.text)
        LOG.debug('Autoblackout close event received, searching for existing blackout')

        # iterate through returned blackouts and match for environment and tag
        # then record the ID of the matching blackout
        blackout_id = ""
        for blackout in blackout_data['blackouts']:
            if blackout['environment'].upper() == alert.environment.upper() and blackout['text'].upper() == alert.event.upper():
                blackout_id = blackout['id']
                break

        # delete the existing blackout
        if blackout_id:
            LOG.debug('Existing blackout found, attempting to delete')
            delete_blackout_url = f'{self.blackout_url}/{blackout_id}'
            try:
                requests.delete(delete_blackout_url, headers=self.authorization_header)
                LOG.debug('Blackout deleted successfully')
            except Exception:
                LOG.error(f'Unable to delete blackout {blackout_id}')

    def pre_receive(self, alert, **kwargs):
        # check to see if this alert is closing out an AUTOBLACKOUT event, and if so, delete the matching blackout
        if alert and BLACKOUT_EVENTS and (alert.status.upper() == 'CLOSED' or alert.severity.upper() == 'NORMAL'):
            for event in BLACKOUT_EVENTS:
                if event.upper() == alert.event.upper():
                    self._delete_blackout(alert)
        return alert

    def post_receive(self, alert, **kwargs):
        if not BLACKOUT_EVENTS:
            LOG.error('No AUTOBLACKOUT_EVENTS defined, aborting autoblackout post_receive function')
            return alert

        # check to see if this alert is opening an AUTOBLACKOUT event, and if so, create a blackout
        if alert and alert.status == 'open':
            for event in BLACKOUT_EVENTS:
                if event.upper() == alert.event.upper():
                    LOG.debug(f'Blackout event {alert.event} identified for alert {alert.id}')
                    self._create_blackout(alert)
        return alert

    def status_change(self, alert, status, text, **kwargs):
        return