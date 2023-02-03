import logging
import os
import http.client
import json
from base64 import b64encode

try:
    from alerta.plugins import app  # alerta >= 5.0
except ImportError:
    from alerta.app import app  # alerta < 5.0
from alerta.plugins import PluginBase

# set plugin logger
LOG = logging.getLogger('alerta.plugins.jira')

# retrieve plugin configurations
JIRA_URL = app.config.get('JIRA_URL') or os.environ.get('JIRA_URL')
JIRA_PROJECT = app.config.get('JIRA_PROJECT') or os.environ.get('JIRA_PROJECT')
JIRA_ACTION_ONLY = app.config.get('JIRA_ACTION_ONLY', False) or os.environ.get('JIRA_ACTION_ONLY', False)
JIRA_USER = app.config.get('JIRA_USER') or os.environ.get('JIRA_USER')
JIRA_PASS = app.config.get('JIRA_PASS') or os.environ.get('JIRA_PASS')

class JiraCreate(PluginBase):
    def __init__ (self, name=None):
        LOG.debug(f'JIRA_ACTION_ONLY is set to {JIRA_ACTION_ONLY}')
        LOG.debug(f'JIRA_PROJECT is set to {JIRA_PROJECT}')
        super(JiraCreate, self).__init__(name)

    def _sendjira(self, resource, event, value, environment, customer, text, severity):
        LOG.info('JIRA: Create task ...')
        userpass = "%s:%s" %(JIRA_USER, JIRA_PASS)
        userAndPass = b64encode(bytes(userpass, "utf-8")).decode("ascii")
        LOG.debug('JIRA_URL: {}'.format(JIRA_URL))
        conn = http.client.HTTPSConnection("%s" %(JIRA_URL))
        
        payload_dict = {
            "fields": {
                "project":
                {
                    "key": "%s" %(JIRA_PROJECT)
                },
                "summary": f"{severity.upper()} - Cluster {resource.upper()}: alert {event.upper()}",
                "description": f"Alert text: {text}\nValue: {value}",
                "environment": f"Customer: {customer}\nEnvironment/Cluster: {environment}/{resource}",
                "issuetype": {
                    "name": "Bug"
                },
            }
        }
        payload = json.dumps(payload_dict, indent = 4)
        headers = {
            'Content-Type': "application/json",
            'Authorization': "Basic %s" %  userAndPass
        }

        conn.request("POST", '/rest/api/2/issue/', payload, headers)
        res = conn.getresponse()
        data = res.read()            
        data = json.loads(data)
        return data["key"]

    def _alertjira(self, alert):
        try:
            LOG.info("Jira: Received an alert")
            LOG.debug("Jira: ALERT       {}".format(alert))
            LOG.debug("Jira: ID          {}".format(alert.id))
            LOG.debug("Jira: CUSTOMER    {}".format(alert.customer))
            LOG.debug("Jira: RESOURCE    {}".format(alert.resource))
            LOG.debug("Jira: ENVIRONMENT {}".format(alert.environment))
            LOG.debug("Jira: EVENT       {}".format(alert.event))
            LOG.debug("Jira: SEVERITY    {}".format(alert.severity))
            LOG.debug("Jira: TEXT        {}".format(alert.text))

            # call the _sendjira and modify de text (discription)
            task = self._sendjira(alert.resource, alert.event, alert.value, alert.environment, alert.customer, alert.text, alert.severity)
            task_url = "https://" + JIRA_URL + "/browse/" + task
            href = '<a href="%s" target="_blank">%s</a>' %(task_url, task)
            alert.attributes = {'Jira Task': href}
            return alert

        except Exception as e:
            LOG.error('Jira: Failed to create task: %s', e)
            return

    # reject or modify an alert before it hits the database
    def pre_receive(self, alert):
        return alert

    # after alert saved in database, forward alert to external systems
    def post_receive(self, alert):
        if not JIRA_ACTION_ONLY:
            # if the alert is critical and don't duplicate, create task in Jira
            if alert.status not in ['ack', 'closed', 'shelved'] and alert.duplicate_count == 0:
                self._alertjira(alert)
                return alert
        else:
            LOG.debug('ignoring new alert because JIRA_ACTION_ONLY is set to True')
            return

    # triggered by external status changes, used by integrations
    def status_change(self, alert, status, text):
        return

    def take_action(self, alert, action, text, **kwargs):
        if action == 'jira':
            if not 'Jira Task' in alert.attributes:
                self._alertjira(alert)
                if 'Jira Task' in alert.attributes:
                    text = "Jira task created"
                else:
                    text = "Jira task creation failed"
            else:
                text = "Jira task already exists for this alert"
        return alert, action, text