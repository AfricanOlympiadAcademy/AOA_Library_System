# run.py
from app import create_app
from app.system_configuration import SystemLaunchConfiguration

app = create_app()

port_value = 5000 if SystemLaunchConfiguration.is_port_free(5000) else 5001

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=port_value)