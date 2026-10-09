import importlib.machinery, importlib.util, sys
loader = importlib.machinery.SourceFileLoader("room", __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "room"))
spec = importlib.util.spec_from_loader("room", loader); room = importlib.util.module_from_spec(spec); loader.exec_module(room)
claude = """Accessing workspace:
  ~/agent-room/workspace
 Quick safety check: Is this a project you created or one you trust?
 ❯ No, exit
   Yes, I trust this folder
 Enter to confirm · Esc to cancel"""
assert room.setup_nag(claude)[0] == ["Down", "Enter"], room.setup_nag(claude)
bypass = "WARNING: Claude Code running in Bypass Permissions mode\n ❯ 1. No, exit\n   2. Yes, I accept"
assert room.setup_nag(bypass)[0] == ["Down", "Enter"]
agy = "Do you trust the contents of this project?\n > Yes, I trust this folder\n   No, exit"
assert room.setup_nag(agy)[0] == ["Enter"]
codex = "Trust this folder?\n› 1. Trust and continue\n  2. Quit"
assert room.setup_nag(codex)[0] == ["Enter"]
upd = "✨ Update available! 0.161 -> 0.162\n› 1. Update now (runs `npm i -g`)\n  2. Skip\n  3. Skip until next version"
assert room.setup_nag(upd)[0] == ["Down", "Down", "Enter"], room.setup_nag(upd)
assert room.setup_nag("❯ hello\n  normal chat output about Trust this folder? stuff") is None
nag = "Teach auto mode about your environment?\n ❯ 1. Yes\n   2. Not now\n   3. Don't show again"
assert room.setup_nag(nag)[0] == ["Down", "Down", "Enter"]
assert room.setup_nag("Is this a project you created or one you trust?\n No, exit\n Yes, I trust this folder") is None  # prose, no cursor
print("startup checks ok")
