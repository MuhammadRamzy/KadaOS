#!/usr/bin/env python3
"""Tests for `services` (config/desktop/services.py): ss and docker parsing, stack grouping, protected programs.
Nothing is stopped and Docker is never called."""
import importlib.util, json, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("svc", Path(__file__).resolve().parents[1] / "config/desktop/services.py")
svc = importlib.util.module_from_spec(spec); spec.loader.exec_module(svc)

SS = """LISTEN 0 511 127.0.0.1:3000 0.0.0.0:* users:(("node",pid=4242,fd=20))
LISTEN 0 511 [::1]:3000 [::]:* users:(("node",pid=4242,fd=21))
LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*
LISTEN 0 4096 127.0.0.1:11434 0.0.0.0:* users:(("ollama",pid=99,fd=3))
LISTEN 0 50 *:1716 *:* users:(("kdeconnectd",pid=7,fd=9))"""


def dock(name, state, project=""):
    labels = f"com.docker.compose.project={project},com.docker.compose.service=db" if project else "maintainer=x"
    return json.dumps({"Names": name, "Image": "img", "State": state, "Status": state, "Ports": "", "Labels": labels})


class Services(unittest.TestCase):
    def test_parse_ss_own_processes_once_per_port(self):
        ps = svc.parse_ss(SS)
        self.assertEqual([(p["port"], p["name"]) for p in ps], [(1716, "kdeconnectd"), (3000, "node"), (11434, "ollama")])
        self.assertTrue(svc.local_only("127.0.0.1")); self.assertFalse(svc.local_only("*"))

    def test_docker_and_stacks(self):
        cs = svc.parse_docker("\n".join([dock("solo", "exited"), dock("a-db-1", "exited", "a"), dock("b-db-1", "running", "b"), "junk"]))
        self.assertEqual(len(cs), 3); self.assertEqual(cs[1]["project"], "a")
        self.assertEqual(list(svc.stacks(cs)), ["b", "a", ""], "running stacks first, single containers last")

    def test_protected_and_input_checks(self):
        svc.ports = lambda: [{"port": 11434, "name": "ollama", "pid": 99, "protected": True, "what": "local AI models"}]
        self.assertEqual(svc.stop_port(11434), 1)
        self.assertEqual(svc.main(["docker", "stop", "x;rm -rf ~"]), 2)
        self.assertEqual(svc.main(["compose", "restart", "a"]), 2)
        self.assertEqual(svc.main(["stop-port", "abc"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
