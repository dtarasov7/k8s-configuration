import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import ROLE, config
from https_fixture import HTTPFixture
from access_manager.client import Client, APIError
from access_manager.schema import AccessError


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = ROLE.parents[1] / ".test-tmp"
        root.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=str(root))
        cls.fixture = HTTPFixture(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.close()
        cls.temp.cleanup()

    def setUp(self):
        self.original = copy.deepcopy(self.fixture.doc)
        self.cfg = config()["connection"]
        self.cfg["kubeconfig"] = str(self.fixture.kubeconfig)
        self.cfg["retries"] = 0

    def tearDown(self):
        self.fixture.doc = self.original
        self.fixture.write_config()

    def test_ca_and_relative_path(self):
        client = Client(self.cfg)
        try:
            self.assertEqual(client.get("/version")["gitVersion"], "v1.30.0")
            self.assertEqual(self.fixture.headers[-1], "Bearer " + self.fixture.secret)
        finally:
            client.close()

    def test_untrusted_ca_rejected(self):
        del self.fixture.doc["clusters"][0]["cluster"]["certificate-authority"]
        self.fixture.write_config()
        client = Client(self.cfg)
        try:
            with self.assertRaises(AccessError):
                client.get("/version")
        finally:
            client.close()

    def test_hostname_mismatch_rejected(self):
        self.fixture.doc["clusters"][0]["cluster"]["server"] = self.fixture.doc["clusters"][0][
            "cluster"
        ]["server"].replace("localhost", "127.0.0.1")
        self.fixture.write_config()
        client = Client(self.cfg)
        try:
            with self.assertRaises(AccessError):
                client.get("/version")
        finally:
            client.close()

    def test_unreachable_redirect_fails_safely(self):
        client = Client(self.cfg)
        try:
            with self.assertRaises(AccessError):
                client.get("/redirect")
        finally:
            client.close()

    def test_server_error_body_never_exposed(self):
        client = Client(self.cfg)
        try:
            with self.assertRaises(APIError) as caught:
                client.get("/forbidden")
            self.assertEqual(caught.exception.status, 403)
            self.assertNotIn(self.fixture.secret, str(caught.exception))
        finally:
            client.close()

    def test_token_file_rotates(self):
        token = self.fixture.root / "token"
        token.write_text(self.fixture.secret)
        self.fixture.doc["users"][0]["user"] = {"tokenFile": "token"}
        self.fixture.write_config()
        client = Client(self.cfg)
        try:
            client.get("/version")
            token.write_text("expired")
            with self.assertRaises(APIError) as caught:
                client.get("/version")
            self.assertEqual(caught.exception.status, 401)
        finally:
            client.close()

    def test_inline_ca_private_and_removed(self):
        self.cfg["ca_content"] = (self.fixture.root / "server.crt").read_text()
        client = Client(self.cfg)
        root = Path(client.tempdir)
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir()))
        client.get("/version")
        client.close()
        self.assertFalse(root.exists())

    def test_exec_credentials_supported(self):
        plugin = self.fixture.root / "credential-plugin.py"
        plugin.write_text(
            "#!" + sys.executable + "\nimport json\nprint(" + repr(json.dumps({
                "apiVersion": "client.authentication.k8s.io/v1", "kind": "ExecCredential",
                "status": {"token": self.fixture.secret},
            })) + ")\n"
        )
        plugin.chmod(0o700)
        self.fixture.doc["users"][0]["user"] = {"exec": {
            "apiVersion": "client.authentication.k8s.io/v1",
            "command": str(plugin), "interactiveMode": "Never",
        }}
        self.fixture.write_config()
        client = Client(self.cfg)
        try:
            self.assertEqual(client.get("/version")["gitVersion"], "v1.30.0")
            self.assertEqual(self.fixture.headers[-1], "Bearer " + self.fixture.secret)
        finally:
            client.close()

    def test_context_is_selected_and_pinned_without_changing_config(self):
        self.fixture.doc["contexts"].append({
            "name": "other", "context": {"cluster": "fixture", "user": "expired"},
        })
        self.fixture.doc["users"].append({"name": "expired", "user": {"token": "expired"}})
        self.fixture.doc["current-context"] = "other"
        self.fixture.write_config()
        before = self.fixture.kubeconfig.read_bytes()
        self.cfg["context"] = "fixture"
        client = Client(self.cfg)
        try:
            self.assertIn("--context=fixture", client.argv)
            client.get("/version")
            self.assertEqual(self.fixture.kubeconfig.read_bytes(), before)
        finally:
            client.close()

    def test_current_context_is_pinned_for_the_entire_run(self):
        client = Client(self.cfg)
        try:
            self.fixture.doc["contexts"].append({
                "name": "other", "context": {"cluster": "fixture", "user": "expired"},
            })
            self.fixture.doc["users"].append({"name": "expired", "user": {"token": "expired"}})
            self.fixture.doc["current-context"] = "other"
            self.fixture.write_config()
            self.assertEqual(client.get("/version")["gitVersion"], "v1.30.0")
            self.assertEqual(self.fixture.doc["current-context"], "other")
        finally:
            client.close()

    def test_unknown_context_and_executable_fail_safely(self):
        for overrides in ({"context": "absent"}, {"kubectl": "/missing/kubectl"}):
            cfg = dict(self.cfg, **overrides)
            with self.assertRaises(AccessError) as caught:
                Client(cfg)
            self.assertNotIn(self.fixture.secret, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
