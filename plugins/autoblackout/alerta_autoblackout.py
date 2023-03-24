import json
import logging
import os
import requests

from alerta.plugins import PluginBase, app

from alerta.models.alert import Alert

# set plugin logger
LOG = logging.getLogger('alerta.plugins.autoblackout')

BASE_URL = app.config.get('BASE_URL') or os.environ.get('BASE_URL')
API_URL = f'http://localhost:8080{BASE_URL}'
API_KEY = os.environ.get('ALERTA_API_KEY') or os.environ.get('ADMIN_KEY')
BLACKOUT_EVENTS = app.config.get('AUTOBLACKOUT_EVENTS') or os.environ.get('AUTOBLACKOUT_EVENTS')

class AutoBlackout(PluginBase):
    def __init__(self, name=None):
        self.blackoutUrl=f'{API_URL}/blackout'
        self.getBlackoutsUrl=f'{API_URL}/blackouts'
        if app.config.get('AUTH_REQUIRED'):
            self.blackoutHeaders={
                "Authorization": f"Key {API_KEY}",
                "Content-type": "application/json"
            }
            self.authorizationHeader={
                "Authorization": f"Key {API_KEY}"
            }
        else:
            self.blackoutHeaders={
                "Content-type": "application/json"
            }
        super(AutoBlackout, self).__init__(name)

    def _createblackout(self, alert):
        if alert.resource == 'kaas-mgmt':
            blackoutDuration = app.config.get('AUTOBLACKOUT_MGMT_DURATION') or app.config.get('BLACKOUT_DURATION')
        else:
            blackoutDuration = app.config.get('AUTOBLACKOUT_CHILD_DURATION') or app.config.get('BLACKOUT_DURATION')
        # construct the blackout request
        blackoutRequest = {
            "duration": blackoutDuration,
            "environment": alert.environment,
            "resource": alert.resource,
            "text": alert.event,
        }
        try:
            # create the blackout
            requests.post(self.blackoutUrl, json=blackoutRequest, headers=self.blackoutHeaders)
            LOG.debug('blackout created successfully')
        except Exception:
            LOG.error(f'Unable to complete POST API request to create blackout for alert {alert.id}')
        return

    def _deleteblackout(self, alert):
        blackoutId = ""
        response = requests.get(self.getBlackoutsUrl, headers=self.authorizationHeader)
        blackout_data = json.loads(response.text)
        LOG.debug('Autoblackout close event received, searching for existing blackout')
        # iterate through returned blackouts and match for environment and tag
        # then record the ID of the matching blackout
        for blackout in blackout_data['blackouts']:
            if str.upper(blackout['environment']) == str.upper(alert.environment):
                if str.upper(blackout['text']) == str.upper(alert.event):
                    blackoutId = blackout['id']
                    break
        # delete the existing blackout
        if blackoutId != "":
            LOG.debug('existing blackout found, attempting to delete')
            deleteBlackoutUrl = f'{self.blackoutUrl}/{blackoutId}'
            requests.delete(deleteBlackoutUrl, headers=self.authorizationHeader)
        return

    def pre_receive(self, alert, **kwargs):
        # check to see if this alert is closing out an AUTOBLACKOUT event, and if so, delete the matching blackout
        if alert is not None:
            if BLACKOUT_EVENTS is None:
                return alert
            # only process when an alert is closed
            if str.upper(alert.status) == 'CLOSED' or str.upper(alert.severity) == 'NORMAL':
                # check that alert event is an AUTOBLACKOUT event
                for event in BLACKOUT_EVENTS:
                    if str.upper(event) == str.upper(alert.event):
                        self._deleteblackout(alert)
        return alert
    
    def post_receive(self, alert, **kwargs):
        # check to see if this alert is opening an AUTOBLACKOUT event, and if so, create a blackout
        if alert is not None:
            if BLACKOUT_EVENTS is None:
                LOG.error('No AUTOBLACKOUT_EVENTS defined, aborting autoblackout post_receive function')
                return alert
            # only process when an alert is opened
            if alert.status == 'open':
                # check that alert event is an AUTOBLACKOUT event
                for event in BLACKOUT_EVENTS:
                    if str.upper(event) == str.upper(alert.event):
                        LOG.debug(f'blackout event {alert.event} identified for alert {alert.id}')
                        self._createblackout(alert)
        return alert

    def status_change(self, alert, status, text, **kwargs):
        return