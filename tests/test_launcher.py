"""Regression checks for the failed launch path, not ecological validation."""
import socket,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from launch_demo import DemoServer,Handler,main,open_offline,WEB

class LauncherTests(unittest.TestCase):
    def test_default_launch_opens_offline_file_without_server(self):
        with patch('sys.argv',['launch_demo.py']),patch('launch_demo.open_offline') as opened,patch('launch_demo.DemoServer') as server:
            main();opened.assert_called_once();server.assert_not_called()

    def test_browser_receives_existing_file_url(self):
        self.assertTrue((WEB/'index.html').is_file())
        with patch('launch_demo.webbrowser.open_new_tab',return_value=True) as opened:
            open_offline();opened.assert_called_once_with((WEB/'index.html').as_uri())

    def test_second_listener_cannot_silently_share_port(self):
        server=DemoServer(('127.0.0.1',0),Handler)
        try:
            with self.assertRaises(OSError):DemoServer(server.server_address,Handler)
        finally:server.server_close()

if __name__=='__main__':unittest.main()
