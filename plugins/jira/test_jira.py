import json
import unittest
from uuid import uuid4

from alerta.app import create_app, plugins
from alerta_jira import JiraCreate

class JiraPluginTestCase(unittest.TestCase):

    def setUp(self) -> None:
        test_config = {
            'TESTING': True,
            'AUTH_REQUIRED': False,
            'BASE_URL': '/api',
            'JIRA_URL': '', #input value
            'JIRA_PROJECT': '', #input value
            'JIRA_ACTION_ONLY': True,
            'JIRA_USER': '', #input value
            'JIRA_PASS': '', #input value
            'CUSTOMER_VIEWS': True
        }
        self.app = create_app(test_config)
        self.client = self.app.test_client()

        self.resource = str(uuid4()).upper()[:8]

        self.major_alert = {
            'event': 'node_marginal',
            'resource': self.resource,
            'environment': 'Production',
            'service': ['Network'],
            'severity': 'major',
            'correlate': ['node_down', 'node_marginal', 'node_up'],
            'timeout': 40
        }

        self.headers = {
            'Content-type': 'application/json',
            'X-Forwarded-For': '10.0.0.1'
        }

    def test_jira_plugin(self):
        plugins.plugins['jira'] = JiraCreate()

        # create alert
        response = self.client.post('/alert', data=json.dumps(self.major_alert), headers=self.headers)
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.data.decode('utf-8'))
        self.assertEqual(data['alert']['resource'], self.resource)
        self.assertEqual(data['alert']['status'], 'open')
        self.assertEqual(data['alert']['duplicateCount'], 0)
        self.assertEqual(data['alert']['trendIndication'], 'moreSevere')

        alert_id = data['id']

        # send to jira
        response = self.client.put('/alert/' + alert_id + '/action',
                                    data=json.dumps({'action': 'jira'}), headers=self.headers)
        self.assertEqual(response.status_code, 200)
        response = self.client.get('/alert/' + alert_id)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data.decode('utf-8'))
        self.assertEqual(data['alert']['severity'], 'major')
        self.assertRegex(data['alert']['attributes']['jira'], "https://mirantis.jira.com/browse/[a-zA-Z]+-[0-9]+")