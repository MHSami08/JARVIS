import os

def modify_core_file(file_path, new_content, mode='w'):
    """
    Safely modifies or creates a core file.
    """
    try:
        # Prevent traversal outside the base directory for safety
        base_dir = os.path.dirname(os.path.abspath(__file__))
        target_path = os.path.abspath(os.path.join(base_dir, '..', file_path))
        
        if not target_path.startswith(os.path.abspath(os.path.join(base_dir, '..'))):
            return {"status": "error", "message": "Access denied: Target path outside project root."}

        with open(target_path, mode) as f:
            f.write(new_content)
        return {"status": "success", "message": f"File '{file_path}' modified successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def run(parameters, response=None, player=None, session_memory=None):
    print(f"DEBUG: Received parameters: {parameters}")
    file_path = parameters.get('file_path')
    content = parameters.get('content')
    mode = parameters.get('mode', 'w') # 'w' for overwrite, 'a' for append

    if not file_path or not isinstance(file_path, str) or not file_path.strip():
        return "Error: 'file_path' parameter is missing, empty, or invalid."
        
    if content is None:
        return "Error: 'content' parameter is missing."

    result = modify_core_file(file_path, content, mode)
    return result['message']

PLUGIN = {
    'name': 'self_modification_system',
    'description': 'Allows dynamic creation and editing of system files.',
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'file_path': {
                'type': 'STRING',
                'description': 'Relative path to the target file'
            },
            'content': {
                'type': 'STRING',
                'description': 'The code or content to write'
            },
            'mode': {
                'type': 'STRING',
                'description': "Write mode: 'w' (standard) or 'a' (append)"
            }
        },
        'required': ['file_path', 'content']
    },
    'run': run
}