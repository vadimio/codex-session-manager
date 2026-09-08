import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from session_rpc import AppServer


class RpcTests(unittest.TestCase):
    def spawn(self, program):
        real_popen = subprocess.Popen
        return patch(
            "session_rpc.subprocess.Popen",
            side_effect=lambda _args, **kwargs: real_popen(
                [sys.executable, "-c", program], **kwargs
            ),
        )

    def test_fragmented_response_and_full_stderr_pipe(self):
        program = """import sys,json
for line in sys.stdin:
    m=json.loads(line)
    if 'id' not in m: continue
    response=json.dumps({'id':m['id'],'result':{'ok':True}})
    sys.stdout.write(response[:8]);sys.stdout.flush()
    sys.stderr.write('x'*200000);sys.stderr.flush()
    sys.stdout.write(response[8:]+'\\n');sys.stdout.flush()
"""
        with tempfile.TemporaryDirectory() as directory, self.spawn(program):
            with AppServer(Path(directory), timeout=2) as server:
                self.assertEqual(server.request("test", {}), {"ok": True})

    def test_partial_line_cannot_bypass_timeout(self):
        program = """import sys,json,time
for line in sys.stdin:
    m=json.loads(line)
    if 'id' not in m: continue
    if m['method']=='initialize':
        print(json.dumps({'id':m['id'],'result':{}}),flush=True)
    else:
        sys.stdout.write('{');sys.stdout.flush();time.sleep(30)
"""
        with tempfile.TemporaryDirectory() as directory, self.spawn(program):
            start = time.monotonic()
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                with AppServer(Path(directory), timeout=0.15) as server:
                    server.request("test", {})
            self.assertLess(time.monotonic() - start, 3)
