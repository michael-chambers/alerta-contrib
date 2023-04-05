import http.client
import json
import logging
import os
from base64 import b64encode
import re

from alerta.plugins import PluginBase

from alerta.plugins import app  # alerta >= 5.0

# set plugin logger
LOG = logging.getLogger('alerta.plugins.jira')

# retrieve plugin configurations
JIRA_URL = app.config.get('JIRA_URL') or os.environ.get('JIRA_URL')
JIRA_PROJECT = app.config.get('JIRA_PROJECT') or os.environ.get('JIRA_PROJECT')
JIRA_ACTION_ONLY = app.config.get('JIRA_ACTION_ONLY', False) or os.environ.get('JIRA_ACTION_ONLY', False)
JIRA_USER = app.config.get('JIRA_USER') or os.environ.get('JIRA_USER')
JIRA_PASS = app.config.get('JIRA_PASS') or os.environ.get('JIRA_PASS')


class JiraCreate(PluginBase):

    def __init__(self, name=None):
        LOG.debug(f'JIRA_ACTION_ONLY is set to {JIRA_ACTION_ONLY}')
        LOG.debug(f'JIRA_PROJECT is set to {JIRA_PROJECT}')
        super(JiraCreate, self).__init__(name)

    @staticmethod
    def _sendjira(alert):
        LOG.info('JIRA: Create task ...')
        userpass = '{}:{}'.format(JIRA_USER, JIRA_PASS)
        user_and_pass = b64encode(bytes(userpass, 'utf-8')).decode('ascii')
        LOG.debug('JIRA_URL: {}'.format(JIRA_URL))
        conn = http.client.HTTPSConnection('%s' % JIRA_URL)
        tags = str.join("\n", alert.tags)

        payload_dict = {
            "fields": {
                "project": {
                    "key": f'{JIRA_PROJECT}'
                },
                "summary": f'{alert.severity.upper()} - {alert.resource}: {alert.event}',
                "description": f'Text: {alert.text}\n\nValue: {alert.value or "N/A"}',
                "customfield_26097": tags,
                "labels": [f'{alert.customer.replace(" ", "")}', f'{alert.environment.replace(" ", "")}'],
                "issuetype": {
                    "name": "Bug"
                }
            }
        }
        LOG.debug(f"payload_dict is: {payload_dict}")
        payload = json.dumps(payload_dict, indent=4)
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic %s' % user_and_pass
        }

        conn.request('POST', '/rest/api/2/issue/', payload, headers)
        res = conn.getresponse()
        data = res.read()
        data = json.loads(data)
        return data["key"]

    def _alertjira(self, alert):
        try:
            LOG.info("Jira: Received an alert")
            LOG.debug("Jira: ALERT       {}".format(alert))
            LOG.debug("Jira: ID          {}".format(alert.id))
            LOG.debug("Jira: CUSTOMER    {}".format(alert.customer.replace(" ", "")))
            LOG.debug("Jira: RESOURCE    {}".format(alert.resource))
            LOG.debug("Jira: ENVIRONMENT {}".format(alert.environment.replace(" ", "")))
            LOG.debug("Jira: EVENT       {}".format(alert.event))
            LOG.debug("Jira: SEVERITY    {}".format(alert.severity))
            LOG.debug("Jira: TEXT        {}".format(alert.text))

            # call _sendjira and modify de text (description)
            task = self._sendjira(alert)
            task_url = "https://" + JIRA_URL + "/browse/" + task
            href = '<a href="%s" target="_blank">%s</a>' % (task_url, task)
            alert.attributes['jira'] = href
            return alert

        except Exception as e:
            LOG.error('Jira: Failed to create task: %s', e)
            return

    # reject or modify an alert before it hits the database
    def pre_receive(self, alert, **kwargs):
        return alert

    # after alert saved in database, forward alert to external systems
    def post_receive(self, alert, **kwargs):
        if not JIRA_ACTION_ONLY:
            # if the alert is critical and don't duplicate, create task in Jira
            if alert.status not in ['ack', 'closed', 'shelved'] and alert.duplicate_count == 0:
                self._alertjira(alert)
                return alert
        else:
            LOG.debug('ignoring new alert because JIRA_ACTION_ONLY is set to True')
            return

    # triggered by external status changes, used by integrations
    def status_change(self, alert, status, text, **kwargs):
        return

    def take_action(self, alert, action, text, **kwargs):
        if action == 'jira':
            if 'jira' not in alert.attributes:
                self._alertjira(alert)
                if 'jira' in alert.attributes:
                    if alert.status == 'open':
                        alert.status = 'ack'
                    text = "Jira task created"
                else:
                    text = "Jira task creation failed"
            else:
                text = "Jira task already exists for this alert"
        return alert, action, text

    def take_note(self, alert, text, **kwargs):
        LOG.debug(f"checking for Jira ticket in note: {text}")
        if re.search("https://mirantis.jira.com/browse/", text):
            LOG.debug("Jira ticket found in note")
            ticket = re.findall("https://mirantis.jira.com/browse/[a-zA-Z]+-[0-9]+", text)[0]
            ticket_id = ticket.split("/")[-1]
            alert.attributes['jira'] = '<a href="%s" target="_blank">%s<a>' % (ticket, ticket_id)
            if alert.status == 'open':
                alert.status = 'ack'
        return alert

    def delete(self, alert, **kwargs) -> bool:
        pass
