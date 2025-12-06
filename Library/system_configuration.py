import socket

class SystemLaunchConfiguration:
    def is_port_free(port):
        """Checks if a given port is free on localhost."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                print(f'port {port} is free')
                return True
            except OSError:
                print(f"port 5000 is not free. port {port} will be used instead")
                return False