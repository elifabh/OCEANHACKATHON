"""Serve only the built demo on loopback, open a browser, and keep it running."""
from __future__ import annotations
import argparse
import functools
import http.server
import json
from pathlib import Path
import threading
import urllib.request
import urllib.parse
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'outputs/map'
# Loopback must not be routed through an inherited corporate/system HTTP proxy.
LOCAL_HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(WEB),**kwargs)
    def log_message(self,*args):pass
    def end_headers(self):
        self.send_header('Cache-Control','no-cache')
        self.send_header('X-Content-Type-Options','nosniff')
        super().end_headers()
    def do_GET(self):
        path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path=='/__health':
            body=json.dumps({'application':'ocean-invisible-shield','build_id':json.loads((WEB/'build_manifest.json').read_text())['build_id']}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
        target=(WEB/path.lstrip('/')).resolve()
        if not target.is_relative_to(WEB.resolve()):self.send_error(403);return
        if target.is_dir() and target!=WEB.resolve():self.send_error(403);return
        super().do_GET()
    def list_directory(self,path):self.send_error(403,'Directory browsing is disabled');return None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--no-browser',action='store_true')
    p.add_argument('--smoke',action='store_true',help='Verify built files via HTTP and exit')
    p.add_argument('--port',type=int,default=8000)
    a=p.parse_args()
    for name in ['index.html','cape_workspace.js','cape_workspace.css','cape_report.js','parametric.js','evidence.json','build_manifest.json','vendor/leaflet/leaflet.js']:
        if not (WEB/name).is_file():raise SystemExit(f'Missing {name}. Run REBUILD_DEMO.bat first.')
    expected=json.loads((WEB/'build_manifest.json').read_text())['build_id']
    server=None
    for port in range(a.port,a.port+10):
        url=f'http://127.0.0.1:{port}'
        try:
            server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);break
        except OSError:
            try:
                with LOCAL_HTTP.open(url+'/__health',timeout=1) as response:health=json.load(response)
                if health.get('application')=='ocean-invisible-shield' and health.get('build_id')==expected:break
            except (OSError,ValueError):continue
    else:raise SystemExit('Ports 8000-8009 are in use. Close an old demo window or specify --port.')
    if a.smoke:
        if server:threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            for path in ['/index.html','/cape_workspace.js','/cape_workspace.css','/cape_report.js','/parametric.js','/evidence.json','/vendor/leaflet/leaflet.js','/__health']:
                with LOCAL_HTTP.open(url+path,timeout=10) as response:
                    if response.status!=200 or not response.read():raise RuntimeError('Empty HTTP response '+path)
            print('PASS: localhost launch and eight HTTP resources, build '+expected)
        finally:
            if server:server.shutdown();server.server_close()
        return
    print('Ocean Hackathon demo: '+url+'/index.html',flush=True)
    if not a.no_browser:webbrowser.open(url+'/index.html')
    if server:
        print('Keep this window open. Press Ctrl+C or close it to stop the server.',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
        finally:server.server_close()
    else:print('Reused the existing local demo server.')


if __name__=='__main__':main()
