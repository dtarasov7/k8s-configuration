"""Execute the packaged role against a real HTTPS endpoint with an API fixture."""
import copy
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import ROLE, grant, config, HASH, FakeAPI
from https_fixture import HTTPFixture


class AnsibleHTTPS(unittest.TestCase):
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
        self.fixture.api = FakeAPI()
        self.original_doc = copy.deepcopy(self.fixture.doc)
        self.export_path = self.fixture.root / "export.yml"
        self.export_path.unlink(missing_ok=True)

    def tearDown(self):
        self.fixture.doc = self.original_doc
        self.fixture.write_config()

    def run_play(self, mode="dry", check=False, grants=None, deckhouse=False, context=None,
                 diff=False, inventory=None, export=None, inventory_file=None, config_extra=None,
                 expected_failure=False):
        cfg = config(deckhouse)
        cfg["mode"] = mode
        cfg["connection"]["kubeconfig"] = str(self.fixture.kubeconfig)
        cfg.update(config_extra or {})
        if context:
            cfg["connection"]["context"] = context
        variables = {
            "ansible_python_interpreter": sys.executable,
            "k8s_configuration_config": cfg,
            "k8s_configuration_grants": grants if grants is not None else [grant()],
            "k8s_configuration_no_log": False,
            "k8s_configuration_export": dict({"destination": str(self.export_path)}, **(export or {})),
        }
        if deckhouse:
            variables["k8s_configuration_users"] = [
                {
                    "name": "jane",
                    "source": "static",
                    "email": "jane@example.org",
                    "password_hash": HASH,
                }
            ]
            variables["k8s_configuration_groups"] = [
                {"name": "devs", "source": "static", "claim_name": "devs", "members": ["jane"]}
            ]
        if inventory is not None:
            variables.update(inventory)
        play = [
            {
                "name": "HTTPS integration",
                "hosts": "localhost",
                "gather_facts": False,
                "vars": variables,
                "roles": ["k8s-configuration"],
            }
        ]
        if inventory_file:
            for key in ("users", "groups", "grants"):
                variables.pop("k8s_configuration_" + key, None)
            play[0]["vars_files"] = [str(inventory_file)]
        path = self.fixture.root / "play.yml"
        path.write_text(yaml.safe_dump(play))
        env = dict(
            os.environ,
            ANSIBLE_LOCAL_TEMP=str(self.fixture.root / "local"),
            ANSIBLE_REMOTE_TEMP=str(self.fixture.root / "remote"),
            ANSIBLE_ROLES_PATH=str(ROLE.parent),
            ANSIBLE_NOCOLOR="1",
            ANSIBLE_HOST_KEY_CHECKING="False",
        )
        cmd = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)]
        if check:
            cmd.append("--check")
        if diff:
            cmd.append("--diff")
        result = subprocess.run(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=45
        )
        if expected_failure:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        else:
            self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("Failure using method", result.stdout)
        self.assertNotIn(self.fixture.secret, result.stdout)
        self.assertNotIn(HASH, result.stdout)
        return result.stdout

    def test_context_does_not_redact_namespace(self):
        self.fixture.doc["contexts"][0]["name"] = "dev"
        self.fixture.doc["current-context"] = "dev"
        self.fixture.write_config()
        self.run_play("apply", context="dev")
        output = self.run_play("export", context="dev")
        self.assertIn("dev", self.export_path.read_text())
        self.assertNotIn("VALUE_SPECIFIED_IN_NO_LOG_PARAMETER", self.export_path.read_text())

    def test_role_package_check_apply_idempotence_and_export(self):
        api = self.fixture.api
        api.calls = []
        output = self.run_play("apply", check=True, diff=True)
        self.assertIn("changed=1", output)
        self.assertIn("before", output)
        self.assertTrue(all(c[0] == "GET" for c in api.calls))
        output = self.run_play("dry")
        self.assertIn("Планируем добавить", output)
        self.assertIn("Планируем изменить", output)
        self.assertIn("Планируем удалить", output)
        self.assertIn("changed=0", output)
        self.assertTrue(all(c[0] == "GET" for c in api.calls))
        output = self.run_play("apply")
        self.assertIn("changed=1", output)
        output = self.run_play("apply")
        self.assertIn("changed=0", output)
        api.calls = []
        self.run_play("export")
        self.assertTrue(all(c[0] == "GET" for c in api.calls))

    def test_deckhouse_identity_secret_redaction_and_noop(self):
        output = self.run_play("apply", grants=[], deckhouse=True)
        self.assertIn('"jane"', output)
        self.assertIn("changed=0", self.run_play("apply", grants=[], deckhouse=True))

    def test_export_file_imports_on_another_cluster_and_contains_standalone_users(self):
        self.run_play("apply", grants=[], deckhouse=True)
        self.fixture.api.calls = []
        self.run_play("export", deckhouse=True, diff=True)
        self.assertTrue(all(c[0] == "GET" for c in self.fixture.api.calls))
        data = yaml.safe_load(self.export_path.read_text())
        self.assertEqual(set(data), {
            "k8s_configuration_users", "k8s_configuration_groups", "k8s_configuration_grants"
        })
        self.assertEqual(data["k8s_configuration_users"][0]["password_hash"], HASH)
        self.assertEqual(self.export_path.stat().st_mode & 0o777, 0o600)
        self.fixture.api = FakeAPI()
        self.assertIn("changed=1", self.run_play("apply", deckhouse=True, inventory_file=self.export_path))
        self.assertIn("changed=0", self.run_play("apply", deckhouse=True, inventory_file=self.export_path))

    def test_export_check_stays_export_and_previews_file_without_writing(self):
        self.run_play("apply")
        self.fixture.api.calls = []
        output = self.run_play("export", check=True)
        self.assertIn("changed=1", output)
        self.assertIn('"grants": "1"', output)
        self.assertFalse(self.export_path.exists())
        self.assertTrue(all(c[0] == "GET" for c in self.fixture.api.calls))

    def test_capture_manually_created_binding_and_import_inventory_unchanged(self):
        self.run_play("apply")
        binding = next(o for o in self.fixture.api.objects.values() if o.get("kind") == "RoleBinding")
        binding["metadata"]["labels"] = {}
        binding["metadata"]["annotations"] = {}
        binding["subjects"] = [{"kind": "User", "name": "manual-user", "apiGroup": "rbac.authorization.k8s.io"}]
        self.run_play("export", export={"mode": "scoped", "cluster_roles": ["view"]})
        data = yaml.safe_load(self.export_path.read_text())
        self.assertEqual(data["k8s_configuration_grants"][0]["subjects"][0]["name"], "manual-user")
        self.fixture.api = FakeAPI()
        self.run_play("apply", inventory=data)
        self.assertIn("changed=0", self.run_play("apply", inventory=data))

    def test_dry_never_server_validates_and_check_is_independent(self):
        for check in (False, True):
            self.fixture.api.calls = []
            output = self.run_play("dry", check=check, config_extra={"server_validation": True})
            self.assertIn("changed=0", output)
            self.assertTrue(all(c[0] == "GET" for c in self.fixture.api.calls))

    def test_apply_diff_with_default_no_log_is_rendered_and_sanitized(self):
        output = self.run_play("apply", diff=True, inventory={"k8s_configuration_no_log": True})
        self.assertIn("--- before: RoleBinding/", output)
        self.assertIn("+++ after: RoleBinding/", output)
        self.assertIn("changed=1", output)

    def test_incomplete_export_fails_with_public_reason_and_writes_no_file(self):
        self.run_play("apply", deckhouse=True, grants=[])
        self.fixture.api.objects["/apis/deckhouse.io/v1/users/jane"]["spec"]["ttl"] = "1h"
        output = self.run_play("export", deckhouse=True, expected_failure=True)
        self.assertIn("unsupported resources or identities", output)
        self.assertFalse(self.export_path.exists())


if __name__ == "__main__":
    unittest.main()
