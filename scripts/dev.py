"""Run the complete ABS demo locally with Python 3.10+ and no packages."""
import argparse,os,sys
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4317);args=parser.parse_args()
config=ROOT/'.env'
if config.exists():
    for line in config.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key,value=line.split('=',1)
            if key.strip().startswith('ABS_'):os.environ.setdefault(key.strip(),value.strip())
os.environ['ABS_ALLOWED_ORIGINS']=f'http://127.0.0.1:{args.port},http://localhost:{args.port}'
os.environ['ABS_WORK_SECURE_COOKIE']='false'
os.environ.setdefault('ABS_API_DATA_DIR',str(ROOT/'.local-data'))
sys.path.insert(0,str(ROOT/'app'))
import abs_api as api

class Handler(api.Handler,SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'app/static/abs'),**kwargs)
    def do_GET(self):
        if self.path.startswith('/api/abs/'):return api.Handler.do_GET(self)
        if self.path=='/abs' or self.path.startswith('/abs/'):
            self.send_response(302);self.send_header('Location',self.path[4:] or '/');self.send_header('Content-Length','0');self.end_headers();return
        return SimpleHTTPRequestHandler.do_GET(self)

server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
print(f'ABS Lens: http://127.0.0.1:{args.port}/ (Ctrl+C to stop)',flush=True)
try:server.serve_forever()
except KeyboardInterrupt:pass
finally:server.server_close()
