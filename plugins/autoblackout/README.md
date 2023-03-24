Autoblackout Plugin 
===========

Automatically creates a blackout for an environment and resource (i.e. cluster-wide) when certain specified alerts are received. Automatically deletes the blackout when the alert that caused its creation is closed.

> Note: This plugin was written specifically to work with Mirantis Container Cloud (MCC) environments.

Installation
------------

Clone the GitHub repo and run:

    $ python setup.py install

Or, to install remotely from GitHub run:

    $ pip install git+https://github.com/michael-chambers/alerta-contrib.git#subdirectory=plugins/autoblackout

Note: If Alerta is installed in a python virtual environment then plugins
need to be installed into the same environment for Alerta to dynamically
discover them.

Configuration
-------------

Add `autoblackout` to the list of enabled `PLUGINS` in `alertad.conf` server
configuration file and set plugin-specific variables either in the
server configuration file or as environment variables.

> Note: this plugin depends on the blackout plugin, which must also be enabled. Additionally, this plugin should be listed before the blackout plugin in the PLUGIN configuration setting.

```python
PLUGINS = ['autoblackout, blackout']            #enable the plugin
NOTIFICATION_BLACKOUT = True                    #allows Alerta to silently accept alerts during blackouts, required
BLACKOUT_ACCEPT = ['normal', 'ok', 'cleared']   #allows Alerta to close alerts received during a blackout, required
BLACKOUT_DURATION = 10800                       #fallback value for blackout duration (in seconds), default is 1 hour
AUTOBLACKOUT_EVENTS = ['MCCClusterUpdating']    #list of alert events to trigger a cluster-wide blackout
AUTOBLACKOUT_MGMT_DURATION = 14400              #value for blackout duration for MCC management clusters, no default
AUTOBLACKOUT_CHILD_DURATION = 86400             #value for blackout duration for MCC child clusters, no default
```

Closing the Triggering Alert
------------------
It is expected that the alert which triggered the blackout will be closed via a "resolved" alert received by Alerta. Due to the nature of how blackouts function in alert, the only way the alert which triggered the alert (which will itself be included in the blackout created) can trigger the deletion of the blackout is to use a `pre_receive` function in the plugin code, which must execute before any `blacklist` plugin code. As a result, this plugin will NOT be able to automatically delete blackouts if it is listed after the `blacklist` plugin in the `PLUGINS` setting in the Alerta server configuration file (alertad.conf). It will also not delete blackouts if the triggering alert is closed or deleted manually in the UI or through the CLI with `alerta close`. It will, however, work when closing an alert through the CLI with `alerta send` where the severity is set to "normal."

Troubleshooting
---------------

Restart Alerta API and confirm that the plugin has been loaded and enabled.

Set `DEBUG=True` in the `alertad.conf` configuration file and look for log
entries similar to below:


Copyright (c) 2023 Mirantis Inc.
