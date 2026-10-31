import base64
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

    def test_redirect_rejected(self):
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
        ca = self.fixture.doc["clusters"][0]["cluster"]
        del ca["certificate-authority"]
        ca["certificate-authority-data"] = base64.b64encode(
            (self.fixture.root / "server.crt").read_bytes()
        ).decode()
        self.fixture.write_config()
        client = Client(self.cfg)
        root = Path(client.tempdir)
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir()))
        client.get("/version")
        client.close()
        self.assertFalse(root.exists())

    def test_exec_and_auth_provider_rejected(self):
        for unsupported in ("exec", "auth-provider", "as", "username"):
            self.fixture.doc["users"][0]["user"] = {unsupported: {}}
            self.fixture.write_config()
            with self.assertRaises(AccessError):
                Client(self.cfg)


if __name__ == "__main__":
    unittest.main()
