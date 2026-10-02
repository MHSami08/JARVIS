import os
import sys

def run(parameters, response=None, player=None, session_memory=None):
    if response:
        response.confirm("Are you sure you want to restart the system?")
    
    if os.name == 'nt':
        os.system('shutdown /r /t 1')
    else:
        os.system('sudo shutdown -r now')

PLUGIN = {
    'name': 'self_restart',
    'description': 'Triggers a system restart with a confirmation prompt.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {}
    },
    'run': run
}