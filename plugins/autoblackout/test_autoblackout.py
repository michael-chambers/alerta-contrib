import json
import unittest
import os

from alerta.app import create_app, plugins
from alerta_autoblackout import AutoBlackout

class AutoBlackoutPluginTestCase(unittest.TestCase):

    def setUp(self) -> None:
        test_config = {
            'TESTING': True,
            'AUTH_REQUIRED': True,
            # 'ADMIN_USERS': ['admin@alerta.io'],
            # 'AUTH_PROVIDER': 'basic',
            'ADMIN_KEY': 'demo-key',
            'BASE_URL': '/api', 
            'CUSTOMER_VIEWS': True,
        }
        self.app = create_app(test_config)
        self.client = self.app.test_client()
        # self.client = current_app.test_client()

        self.open_updatealert = {
            # 'customer': 'Netskope',
            'event': 'MCCClusterUpdating',
            'resource': 'kaas-mgmt',
            'environment': 'Production',
            'service': ['mcc'],
            'severity': 'informational',
            'timeout': 86400
        }

        self.headers = {
            'Authorization': 'Key demo-key',
            'Content-type': 'application/json',
        }

    def test_autoblackout_plugin(self):
        plugins.plugins['autoblackout'] = AutoBlackout()

        # create alert
        response = self.client.post('/alert', data=json.dumps(self.open_updatealert), headers=self.headers)
        self.assertEqual(response.status_code, 201)
