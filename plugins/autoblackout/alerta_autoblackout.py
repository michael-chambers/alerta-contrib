import json
import logging
import os
import re
import requests

from alerta.plugins import PluginBase, app

LOG = logging.getLogger('alerta.plugins.autoblackout')

BASE_URL = app.config.get('BASE_URL') or os.environ.get('BASE_URL')
API_URL = f'http://localhost:8080{BASE_URL}'
API_KEY = os.environ.get('ALERTA_API_KEY') or os.environ.get('ADMIN_KEY')
BLACKOUT_EVENTS = app.config.get('AUTOBLACKOUT_EVENTS') \
    or os.environ.get('AUTOBLACKOUT_EVENTS')
MGMT_CLUSTER_NAME = 'kaas-mgmt'


def get_cluster_from_text(text):
    cluster = re.findall("(?<=\/)\S+", text)[0]
    if cluster:
        return cluster


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

    def _create_blackout(self, alert, cluster):
        blackout_duration = app.config.get(
            'AUTOBLACKOUT_MGMT_DURATION' if cluster == MGMT_CLUSTER_NAME
            else 'AUTOBLACKOUT_CHILD_DURATION') \
                or app.config.get('BLACKOUT_DURATION')

        blackout_request = {
            "duration": blackout_duration,
            "environment": alert.environment,
            "resource": cluster,
            "text": alert.event,
        }
        try:
            # create the blackout
            requests.post(
                self.blackout_url,
                json=blackout_request,
                headers=self.blackout_headers,
                timeout=30)
            LOG.debug('Blackout created successfully')
        except TimeoutError:
            LOG.error(
                f'Request to create blackout timed-out for alert {alert.id}')
        except ConnectionError:
            LOG.error(f'Unable to create blackout for alert {alert.id}')

    def _delete_blackout(self, alert, cluster):
        try:
            response = requests.get(
                self.get_blackouts_url,
                headers=self.authorization_header) \
                    if app.config.get('AUTH_REQUIRED') else requests.get(
                        self.get_blackouts_url,
                        timeout=30)
        except TimeoutError:
            LOG.error(
                'Time-out error when retrieving list of current blackouts')
            return
        except ConnectionError:
            LOG.error('Unable to retrieve list of current blackouts')
            return

        blackout_data = json.loads(response.text)
        LOG.debug(
            '''Autoblackout close event received,
            searching for existing blackout''')

        # iterate through returned blackouts and match for environment and tag
        # then record the ID of the matching blackout
        blackout_id = ""
        for blackout in blackout_data['blackouts']:
            if blackout['environment'].upper() == alert.environment.upper() \
                    and blackout['text'].upper() == alert.event.upper() \
                    and blackout['resource'] == cluster:
                blackout_id = blackout['id']
                break

        # delete the existing blackout
        if blackout_id:
            LOG.debug('Existing blackout found, attempting to delete')
            delete_blackout_url = f'{self.blackout_url}/{blackout_id}'
            try:
                requests.delete(
                    delete_blackout_url,
                    headers=self.authorization_header,
                    timeout=30)
                LOG.debug('Blackout deleted successfully')
            except TimeoutError:
                LOG.error(
                    f'Request timed-out to delete blackout {blackout_id}')
            except ConnectionError:
                LOG.error(f'Unable to delete blackout {blackout_id}')

    def pre_receive(self, alert, **kwargs):
        # check to see if this alert is closing out an AUTOBLACKOUT event
        # if so, delete the matching blackout
        if alert and BLACKOUT_EVENTS \
                and (
                    alert.status.upper() == 'CLOSED'
                    or alert.severity.upper() == 'NORMAL'):
            for event in BLACKOUT_EVENTS:
                if event.upper() == alert.event.upper():
                    cluster = get_cluster_from_text(alert.text)
                    if cluster.upper() == alert.resource.upper():
                        self._delete_blackout(alert, cluster)
        return alert

    def post_receive(self, alert, **kwargs):
        if not BLACKOUT_EVENTS:
            LOG.error(
                '''No AUTOBLACKOUT_EVENTS defined,
                aborting autoblackout post_receive function''')
            return alert

        # check to see if this alert is opening an AUTOBLACKOUT event
        # if so, create a blackout
        if alert and alert.status == 'open':
            for event in BLACKOUT_EVENTS:
                if event.upper() == alert.event.upper():
                    LOG.debug(
                        f'''Blackout event {alert.event}
                        identified for alert {alert.id}''')
                    cluster = get_cluster_from_text(alert.text)
                    if cluster:
                        self._create_blackout(alert, cluster)
                    else:
                        LOG.error(
                            '''Cluster name missing from alert description,
                            unable to create blackout''')
        return alert

    def status_change(self, alert, status, text, **kwargs):
        return
