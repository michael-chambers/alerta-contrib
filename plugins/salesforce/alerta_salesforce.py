import fcntl
import hashlib
import logging
import time
import re
import os
import requests
import json

from contextlib import contextmanager
from cachetools import TTLCache
from requests import Session
from requests.exceptions import ConnectionError as RequestsConnectionError

from simple_salesforce import Salesforce
from simple_salesforce import exceptions as sf_exceptions

from alerta.plugins import PluginBase, app


STATE_MAP = {
    'OK': '060 Informational',
    'UP': '060 Informational',
    'INFORMATIONAL': '060 Informational',
    'UNKNOWN': '070 Unknown',
    'WARNING': '080 Warning',
    'MINOR': '080 Warning',
    'MAJOR': '090 Critical',
    'CRITICAL': '090 Critical',
    'DOWN': '090 Critical',
    'UNREACHABLE': '090 Critical',
}

CONFIG_FIELD_MAP = {
    'auth_url': 'instance_url',
    'username': 'username',
    'password': 'password',
    'organization_id': 'organizationId',
    'environment_id': 'environment_id',
    'sandbox_enabled': 'domain',
    'feed_enabled': 'feed_enabled',
    'hash_func': 'hash_func',
}


ALLOWED_HASHING = ('md5', 'sha256')
SESSION_FILE = '/tmp/session'

SALESFORCE_CONFIG = 'temp_configuration'

LOG = logging.getLogger('alerta.plugins.salesforce')

BASE_URL = app.config.get('BASE_URL') or os.environ.get('BASE_URL')
API_URL = f'http://localhost:8080{BASE_URL}'
API_KEY = os.environ.get('ALERTA_API_KEY') or os.environ.get('ADMIN_KEY')
TIMEOUT_VALUE = 30


@contextmanager
def flocked(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except IOError:
        LOG.info('Session file locked. Waiting 5 seconds...')
        time.sleep(5)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


def sf_auth_retry(method):
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except sf_exceptions.SalesforceExpiredSession:
            LOG.warning('Salesforce session expired.')
            self.auth()
        except RequestsConnectionError:
            LOG.error('Salesforce connection error.')
            self.auth()
        return method(self, *args, **kwargs)
    return wrapper


def get_sf_env_credentials(customer, environment, cluster_name):
    env_id = ""
    username = ""
    password = ""
    try:
        env_clusters = app.config.get(
            'OPSCARE_CUSTOMER_INFO'
            )[customer]['environments'][environment]
        LOG.debug(f'env_clusters are {env_clusters}')
        for cluster_id, cluster_info in env_clusters.items():
            if cluster_info['name'] == cluster_name:
                if 'sf_env_id' in cluster_info.keys():
                    env_id = cluster_info['sf_env_id']
                if 'sf_username' in cluster_info.keys():
                    username = cluster_info['sf_username']
                if 'sf_password' in cluster_info.keys():
                    password = cluster_info['sf_password']
                break
        # if any values weren't found at the cluster level
        # look for them in the environment level
        if not env_id:
            env_id = env_clusters['sf_env_id']
        if not username:
            username = env_clusters['sf_username']
        if not password:
            password = env_clusters['sf_password']
    except Exception as e:
        LOG.error(
            f'''Unable to find SFDC credentials
            for {environment}/{cluster_name}: {e}''')
    return env_id, username, password


def read_sf_auth_values(customer, environment, cluster_name):
    try:
        env_id, username, password = get_sf_env_credentials(
            customer, environment, cluster_name)
        values = {
            'AUTH_URL': f'instance_{customer.replace(" ", "-")}_{environment.replace(" ", "-")}_{cluster_name.replace(" ", "-")}',
            'USERNAME': username,
            'PASSWORD': password,
            'ORGANIZATION_ID': app.config.get('OPSCARE_CUSTOMER_INFO')[customer]['sf_org_id'],
            'ENVIRONMENT_ID': env_id,
            'SANDBOX_ENABLED': app.config.get('SFDC_SANDBOX_ENABLED', False),
            'FEED_ENABLED': app.config.get('SFDC_FEED_ENABLED', False),
            'HASH_FUNC': app.config.get('SFDC_HASH_FUNC', '')
        }
        LOG.debug(f'SFDC values read from alertad.conf: {values}')
        return values
    except Exception as e:
        LOG.error(e)


class SfNotifierError(Exception):
    pass


class SFIntegration(PluginBase):
    def __init__(self, name=None):
        if app.config.get('AUTH_REQUIRED'):
            self.headers = {
                "Authorization": f"Key {API_KEY}",
                "Content-type": "application/json"
            }
        else:
            self.headers = {
                "Content-type": "application/json"
            }
        super(SFIntegration, self).__init__(name)

    def pre_receive(self, alert, **kwargs):
        return alert

    def post_receive(self, alert, **kwargs):
        if alert.event == 'HeartbeatFail':
            alert.severity = 'Critical'
            LOG.debug(f'Sending HeartbeatFail alert for {alert.resource} to SFDC')
            self.take_action(alert, 'salesforce', '', skip_jira_check="True")
            LOG.debug(f'HeartbeatFail alert sent for {alert.resource}')
        elif alert.event == 'KubeDeploymentOutage' \
                and re.search("'stacklight/sf-notifier'", alert.text) \
                and 'salesforce' not in alert.attributes.keys():
            LOG.debug(
                f'Sending alert to SFDC for failure of \
                      sf-notifier pod in {alert.environment}/{alert.resource}')
            alert, action, text = self.take_action(
                alert, "salesforce", "", skip_jira_check="True")
            LOG.debug(
                f"Attempting to add SFDC case ID \
                    {alert.attributes['salesforce']} to alert {alert.id}")
            attribute_request = {
                "attributes": {
                    "salesforce": alert.attributes['salesforce']
                }
            }
            requests.put(
                f"{API_URL}/alert/{alert.id}/attributes",
                headers=self.headers,
                timeout=TIMEOUT_VALUE,
                data=json.dumps(attribute_request))
        return

    def status_change(self, alert, status, text, **kwargs):
        return alert

    def take_action(self, alert, action, text, **kwargs):
        if action == 'salesforce':
            configValues = read_sf_auth_values(alert.customer, alert.environment, alert.resource)
            self.client = SalesforceClient(configValues)
            if 'salesforce' not in alert.attributes.keys() \
                    and ('jira' in alert.attributes.keys() or kwargs['skip_jira_check'] == "True"):
                LOG.debug("Preparing to send alert to SalesForce")
                sf_response = self.client.create_case(
                    f'SRE [{alert.severity.upper()}] {alert.event}',
                    alert.text,
                    alert.serialize)
                LOG.debug(f"sf_response received with status of {sf_response['status']}")
                if sf_response['status'] == 'created':
                    case_link = "https://mirantis.my.salesforce.com/{}"\
                        .format(sf_response['case_id'])
                    alert.attributes['salesforce'] = '<a href="%s" target="_blank">%s<a>' \
                        % (case_link, sf_response['case_id'])
                    text = "SalesForce case created"
                elif sf_response['status'] == 'duplicate':
                    text = "SalesForce case exists for this alert"
                else:
                    text = "Failed to create SalesForce case, check logs"
            elif 'salesforce' in alert.attributes.keys():
                text = "SalesForce case already created for this alert"
            else:  # only remaining possibility is if a Jira issue is required
                text = "JIRA issue required before creating SalesForce case"
        return alert, action, text

    def take_note(self, alert, text, **kwargs):
        LOG.debug(f"checking for SFDC ticket in note: {text}")
        if re.search("https://mirantis\.my\.salesforce\.com/", text):
            LOG.debug("SFDC legacy URL in note")
            ticket_url = re.findall("https://mirantis\.my\.salesforce\.com/[a-zA-Z0-9]{15}", text)[0]
            ticket_id = ticket_url.split("/")[-1]
            alert.attributes['salesforce'] = '<a href="%s" target="_blank">%s<a>' \
                % (ticket_url, ticket_id)
        elif re.search("https://mirantis.lightning.force.com/", text):
            LOG.debug("SFDC Lightning URL found in note")
            ticket_url = re.findall(
                "https://mirantis\.lightning\.force\.com/lightning/r/(?:[Cc]ase/)?[a-zA-Z0-9]{18}\S*",
                text)[0]
            ticket_id = re.findall("(?<=lightning/r/)(?:[Cc]ase/)?([a-zA-Z0-9]{18})", text)[0]
            alert.attributes['salesforce'] = '<a href="%s" target="_blank">%s<a>' % (ticket_url, ticket_id)
        return alert


class SalesforceClient(object):
    def __init__(self, config):
        self.metrics = {
            'sf_auth_ok': False,
            'sf_error_count': 0,
            'sf_request_count': 0
        }
        self._registered_alerts = TTLCache(maxsize=2048, ttl=300)

        self.config = self._validate_config(config)
        self.hash_func = self._hash_func(self.config.pop('hash_func'))
        self.feed_enabled = self.config.pop('feed_enabled')

        self.environment = self.config.pop('environment_id')
        self.sf = None
        self.session = Session()
        self.auth(no_retry=True)
        LOG.debug("SFDC client initialized")

    @staticmethod
    def _hash_func(name):
        if name in ALLOWED_HASHING:
            return getattr(hashlib, name)
        msg = ('Invalid hashing function "{}".'
               'Switching to default "sha256".').format(name)
        LOG.warn(msg)
        return hashlib.sha256

    @staticmethod
    def _validate_config(config):
        kwargs = {}

        for param, value in config.items():
            field = CONFIG_FIELD_MAP.get(param.lower())
            if field is None:
                msg = ('Invalid config: missing "{}" field or "{}" environment'
                       ' variable.').format(field, param)
                LOG.error(msg)
                raise SfNotifierError(msg)

            kwargs[field] = value

            if field == 'domain':
                if value:
                    kwargs[field] = 'test'
                else:
                    del kwargs[field]

        return kwargs

    def _auth(self, config):
        try:
            config.update({'session': self.session})
            self.sf = Salesforce(**config)
        except Exception as ex:
            LOG.error('Salesforce authentication failure: {}.'.format(ex))
            self.metrics['sf_auth_ok'] = False
            return False

        LOG.info('Salesforce authentication successful.')
        self.metrics['sf_auth_ok'] = True
        return True

    def _load_session(self, session_file):
        lines = session_file.readlines()

        if lines == []:
            return
        return lines[0]

    def _refresh_ready(self, saved_session):
        if saved_session is None:
            LOG.info('Current session is None.')
            return True

        if self.sf is None:
            return False

        if self.sf.session_id == saved_session:
            return True
        return False

    def _reuse_session(self, saved_session):
        LOG.info('Reusing session id from file.')
        # limit params to avoid login request
        config = {
            'session_id': saved_session,
            'instance_url': self.config['instance_url']
        }
        return self._auth(config)

    def _acquire_session(self):
        # only one worker at a time can check session_file
        auth_success = False

        LOG.info('Attempting to lock session file.')
        with open(SESSION_FILE, 'r+') as session_file:
            with flocked(session_file):
                LOG.info('Successfully locked session file for refresh.')

                saved_session = self._load_session(session_file)

                if self._refresh_ready(saved_session):
                    LOG.info('Attempting to refresh session.')

                    if self._auth(self.config):
                        auth_success = True
                        session_file.truncate(0)
                        session_file.seek(0)
                        session_file.write(self.sf.session_id)
                        LOG.info('Refreshed session successfully.')
                    else:
                        LOG.error('Failed to refresh session.')
                else:
                    LOG.info('Not refreshing. Reusing session.')
                    auth_success = self._reuse_session(saved_session)

        if auth_success is False:
            LOG.warn('Waiting 30 seconds before next attempt...')
            time.sleep(30)

        return auth_success

    def auth(self, no_retry=False):
        LOG.debug("Attempting to acquire SFDC sesion")
        auth_ok = self._acquire_session()

        if no_retry:
            return

        while auth_ok is False:
            auth_ok = self._acquire_session()

    def _get_alert_id(self, labels):
        alert_id_data = ''
        for key in sorted(labels):
            alert_id_data += labels[key].replace(".", "\\.")
        return self.hash_func(alert_id_data.encode('utf-8')).hexdigest()

    @sf_auth_retry
    def _create_case(self, subject, body, labels, alert_id):

        if alert_id in self._registered_alerts:
            LOG.warning('Duplicate case for alert: {}.'.format(alert_id))
            return 1, self._registered_alerts[alert_id]['Id']

        severity = labels.get('severity', 'unknown').upper()
        services = labels.get('service', 'UNKNOWN')
        if isinstance(services, list):
            if len(services) >= 1:
                service = services[0]
            else:
                service = 'UKNOWN'
        else:
            service = services
        payload = {
            'Subject': subject,
            'Description': body,
            'IsMosAlert__c': 'true',
            'Alert_Priority__c': STATE_MAP.get(severity, '070 Unknown'),
            'Alert_Host__c': labels.get('resource') or labels.get(
                'instance', 'UNKNOWN'
            ),
            'Alert_Service__c': service,
            'Environment2__c': self.environment,
            'Alert_ID__c': alert_id,
            'ClusterId__c': labels['attributes'].get('cluster_id', '')
        }

        LOG.info('Try to create case: {}.'.format(payload))
        try:
            self.metrics['sf_request_count'] += 1
            case = self.sf.Case.create(payload)
            LOG.info('Created case: {}.'.format(case))
        except sf_exceptions.SalesforceMalformedRequest as ex:
            msg = ex.content[0]['message']
            err_code = ex.content[0]['errorCode']

            if err_code == 'DUPLICATE_VALUE':
                LOG.warning('Duplicate case: {}.'.format(msg))
                case_id = msg.split()[-1]
                self._registered_alerts[alert_id] = {'Id': case_id}
                return 1, case_id

            LOG.error('Cannot create case: {}.'.format(msg))
            self.metrics['sf_error_count'] += 1
            raise

        self._registered_alerts[alert_id] = {'Id': case['id']}
        return 0, case['id']

    @sf_auth_retry
    def _create_feed_item(self, subject, body, case_id):
        feed_item = {'Title': subject, 'ParentId': case_id, 'Body': body}
        LOG.debug('Creating feed item: {}.'.format(feed_item))
        return self.sf.FeedItem.create(feed_item)

    def create_case(self, subject, body, labels):
        LOG.debug("Attempting to create SFDC case")
        # alert_id = self._get_alert_id(labels)
        alert_id = labels.get('id')

        error_code, case_id = self._create_case(subject, body,
                                                labels, alert_id)

        response = {'case_id': case_id, 'alert_id': alert_id}

        if error_code == 1:
            response['status'] = 'duplicate'
        else:
            response['status'] = 'created'

        if self.feed_enabled:
            self._create_feed_item(subject, body, case_id)
        return response
