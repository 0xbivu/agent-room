import importlib.machinery, importlib.util, os, tempfile, time
loader = importlib.machinery.SourceFileLoader("room", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "room"))
spec = importlib.util.spec_from_loader("room", loader); room = importlib.util.module_from_spec(spec); loader.exec_module(room)
scratch = tempfile.TemporaryDirectory(prefix="room-catchup-check-")
room.DIR = scratch.name
room.SESSIONS = scratch.name
os.mkdir(os.path.join(scratch.name, "20000101-000000"))
now = time.time()
msgs = [{"id": 1, "from": "user", "text": "old before router", "ts": now}]
new = [{"id": 2, "from": "user", "text": "plan the db", "ts": now},            # -> claude only
       {"id": 3, "from": "claude", "text": "@codex do schema", "ts": now},     # -> codex
       {"id": 4, "from": "user", "text": "/who", "ts": now},                   # command, not context
       {"id": 5, "from": "user", "text": "@all status?", "ts": now}]
pasted = []
live = {n: ("%" + n, n, now - 100, "team") for n in room.CORE}
class Stop(BaseException): pass
calls = {"n": 0}
def api(path, data=None):
    if path == "/messages": return msgs
    if path.startswith("/messages?since="):
        if calls["n"] == 0:
            calls["n"] += 1; return new
        return []
    if path == "/session": return {"id": "20000101-000000"}
    if path == "/sessions": return {"sessions": []}
    return {}
room.api = api; room.agents = lambda: live; room.tmux = lambda *a, **kw: ""; room.last_lines = lambda *a: "❯ "
room.model_lists = lambda: {}; room.record_conversations = lambda live: None; room.main = lambda argv: print("cmd", argv)
room.subprocess.run = lambda args, **kw: pasted.append((args, kw.get("input"))) if "load-buffer" in args else None
sleeps = {"n": 0}
def sleep(t):
    sleeps["n"] += 1
    if sleeps["n"] > 40: raise Stop
room.time.sleep = sleep
room.WARMUP = 0
try: room.router()
except Stop: pass
got = [t for _, t in pasted]
agy = [t for t in got if "#5" in t and "catch-up: 2" in t]
print("\n=====\n".join(got))
assert len(got) == 5, len(got)  # claude#2, codex#3, then #5 to all three
for_all = got[2:]
assert any("plan the db" in t and "do schema" in t and "/who" not in t and "old before" not in t for t in for_all)  # agy saw both
assert all("[room #5]" in t for t in for_all)
print("catch-up ok")
scratch.cleanup()
