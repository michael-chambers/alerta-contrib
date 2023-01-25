SalesForce Plugin
=================

Send alerts to SalesForce.com with a button click. This plugin is heavily customized for use at Mirantis, Inc.

Installation
------------

Clone the GitHub repo and run:

    $ python setup.py install

Or, to install remotely from GitHub run:

    $ pip install git+https://github.com/michael-chambers/alerta-contrib.git#subdirectory=plugins/salesforce

Note: If Alerta is installed in a python virtual environment then plugins
need to be installed into the same environment for Alerta to dynamically
discover them.

Configuration
-------------

Add `salesforce` to the list of enabled `PLUGINS` and web UI `ACTIONS` in the `alertad.conf` server configuration file.

```python
ACTIONS = ['salesforce']
PLUGINS = ['salesforce']
```

Additional variables in `alertad.conf` are shown below. Describe customer environments in the `OPSCARE_CUSTOMER_INFO` variable, which is also utilized by the `normalise` plugin. See the example values below.

```python
SFDC_SANDBOX_ENABLED = False
SFDC_FEED_ENABLED = False
SFDC_HASH_FUNC = ''
OPSCARE_CUSTOMER_INFO = {
    'Customer1': {
        'environments': {
            'environment1': {
                'cluster1_id_XXXXXX': {
                    ...,
                    'sf_env_id': 'XXXXXX'
                },
                'cluster2_id_XXXXXX': {
                    ...,
                    'sf_env_id': 'XXXXXX'
                },
                'sf_username': 'XXXXXX'
                'sf_password': 'XXXXXX'
            }
        },
        'sf_org_id': 'XXXXXX'
    },
    'Customer2': {
        'environments': {
            'environment2': {
                'cluster3_id_XXXXXX': {
                    ...,
                    'sf_env_id': 'XXXXXX',
                    'sf_env_username': 'XXXXXX',
                    'sf_env_password': 'XXXXXX'
                }
            }
        },
        'sf_org_id': 'XXXXXX'
    }
}
```