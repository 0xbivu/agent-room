import json, os, re, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DATA = '/data'
SESSIONS = os.path.join(DATA, 'sessions')
lock = threading.RLock()
msgs, state = [], {}
session = None
LOG = os.path.join(DATA, 'chat.jsonl')
sequence = 0


def read_log(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path, value):
    with open(path + '.tmp', 'w') as f:
        json.dump(value, f)
    os.replace(path + '.tmp', path)


def shared_dir(path):
    os.makedirs(path, exist_ok=True)
    if os.geteuid() == 0:
        owner = os.stat(DATA)
        os.chown(path, owner.st_uid, owner.st_gid)
    os.chmod(path, 0o755)


def session_path(sid):
    if not isinstance(sid, str) or not re.fullmatch(r'\d{8}-\d{6}', sid):
        raise ValueError('invalid session id')
    time.strptime(sid, '%Y%m%d-%H%M%S')
    return os.path.join(SESSIONS, sid)


def activate(sid):
    global session, LOG, msgs, sequence
    path = session_path(sid)
    if not os.path.isdir(path):
        raise FileNotFoundError('no such session')
    history = read_log(os.path.join(path, 'chat.jsonl'))
    sequence += 1
    restored = [{'id': sequence, 'from': 'room', 'text': f'--- room session {sid} ---',
                 'ts': time.time(), 'session': sid, 'reset': True}]
    for message in history:
        sequence += 1
        restored.append({**message, 'id': sequence, 'replay': True})
    write_json(os.path.join(DATA, 'message-id.json'), sequence)
    write_json(os.path.join(DATA, 'active-session.json'), sid)
    session, LOG, msgs = sid, os.path.join(path, 'chat.jsonl'), restored
    state.clear()
    return {'id': sid}


def new_session():
    shared_dir(SESSIONS)
    offset = 0
    while True:
        sid = time.strftime('%Y%m%d-%H%M%S', time.localtime(time.time() + offset))
        if not os.path.exists(session_path(sid)):
            break
        offset += 1
    shared_dir(session_path(sid))
    return activate(sid)


def sessions():
    rows = []
    if os.path.isdir(SESSIONS):
        for sid in sorted(os.listdir(SESSIONS), reverse=True):
            if not re.fullmatch(r'\d{8}-\d{6}', sid) or not os.path.isdir(session_path(sid)):
                continue
            history = read_log(os.path.join(session_path(sid), 'chat.jsonl'))
            try:
                with open(os.path.join(session_path(sid), 'agents.json')) as f:
                    roster = json.load(f)
            except FileNotFoundError:
                roster = []
            rows.append({'id': sid, 'started': time.strftime('%Y-%m-%d %H:%M:%S', time.strptime(sid, '%Y%m%d-%H%M%S')),
                         'agents': [a['name'] for a in roster], 'messages': len(history),
                         'title': next((m['text'].splitlines()[0][:100] for m in history if m['from'] == 'user'), ''),
                         'current': sid == session})
    return {'current': session, 'sessions': rows}


def initialize():
    global msgs, sequence
    msgs = read_log(LOG)
    try:
        with open(os.path.join(DATA, 'message-id.json')) as f:
            sequence = json.load(f)
    except FileNotFoundError:
        sequence = 0
    sequence = max(sequence, max((m['id'] for m in msgs), default=0))
    try:
        with open(os.path.join(DATA, 'active-session.json')) as f:
            sid = json.load(f)
    except FileNotFoundError:
        return  # keep the legacy chat until room up starts the first room session
    activate(sid)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(b))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/':
            b = open('index.html', 'rb').read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', len(b))
            self.end_headers()
            return self.wfile.write(b)
        with lock:
            if u.path == '/state':
                return self.send(200, state)
            if u.path == '/session':
                return self.send(200, {'id': session})
            if u.path == '/sessions':
                return self.send(200, sessions())
            if u.path == '/messages':
                since = int(parse_qs(u.query).get('since', ['0'])[0])
                return self.send(200, [m for m in msgs if m['id'] > since])
        self.send(404, {'error': 'not found'})

    def do_POST(self):
        global sequence
        try:
            d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if not isinstance(d, dict):
                raise ValueError('need a JSON object')
            with lock:
                if self.path == '/sessions/new':
                    return self.send(200, new_session())
                if self.path == '/sessions/resume':
                    return self.send(200, activate(d.get('id')))
                if self.path == '/state':
                    state.clear()
                    state.update(d)
                    return self.send(200, {'ok': True})
                name, text = str(d['from'])[:32], str(d.get('text', ''))[:100_000]
                if self.path not in ('/messages', '/clear') or not text.strip():
                    return self.send(400, {'error': 'bad request'})
                sequence += 1
                write_json(os.path.join(DATA, 'message-id.json'), sequence)
                m = {'id': sequence, 'from': name, 'text': text, 'ts': time.time()}
                if self.path == '/clear':
                    if os.path.exists(LOG):
                        os.rename(LOG, os.path.join(os.path.dirname(LOG), f'chat-{time.time_ns()}.jsonl'))
                    msgs.clear()
                    m['reset'] = True
                with open(LOG, 'a') as f:
                    f.write(json.dumps(m) + '\n')
                msgs.append(m)
            self.send(200, m)
        except FileNotFoundError as e:
            self.send(404, {'error': str(e)})
        except (ValueError, KeyError, TypeError) as e:
            self.send(400, {'error': str(e)})
        except OSError as e:
            self.send(500, {'error': str(e)})


if __name__ == '__main__':
    initialize()
    ThreadingHTTPServer(('0.0.0.0', 8765), H).serve_forever()
