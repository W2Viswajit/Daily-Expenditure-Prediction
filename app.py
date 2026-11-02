"""Run python app.py; local, single-user tracker on port 8502."""
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from threading import RLock,Thread
from pathlib import Path
import json,argparse
import core
lock=RLock();training={'running':False,'message':''}
def worker():
    try:
        with lock:core.train()
        training.update(running=False,message='Both models trained. You can predict now.')
    except Exception as e:training.update(running=False,message=str(e))
class Handler(BaseHTTPRequestHandler):
    def reply(self,value,status=200,kind='application/json'):
        raw=json.dumps(value).encode() if kind=='application/json' else value
        self.send_response(status);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/state':
            if training['running']:return self.reply({'training':training})
            with lock:self.reply(dict(core.state(),training=training))
        elif self.path in ['/','/regression','/classification']:
            self.reply((core.ROOT/'web.html').read_bytes(),kind='text/html')
        elif self.path=='/theme.css':self.reply((core.ROOT/'theme.css').read_bytes(),kind='text/css')
        else:self.reply({'error':'Not found'},404)
    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and origin not in [f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}']:return self.reply({'error':'Local origin required'},403)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=7*1024*1024:raise ValueError('Invalid request size')
            p=json.loads(self.rfile.read(n));action=self.path.strip('/')
            if training['running']:raise ValueError('Training in progress; please wait.')
            if action=='train':
                training.update(running=True,message='Training expense and incoming-money models…');Thread(target=worker,daemon=True).start();return self.reply(training)
            with lock:
                if action=='predict':result=core.forecast(p['date'])
                elif action=='history-delete':
                    with core.db() as c:c.execute('DELETE FROM forecasts WHERE id=?',(int(p['id']),))
                    result={'saved':True}
                else:result=core.mutate(action,p)
            self.reply(result)
        except Exception as e:self.reply({'error':str(e)},400)
    def log_message(self,*args):pass
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8502);args=parser.parse_args()
    print(f'Personal Expense Tracker: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
