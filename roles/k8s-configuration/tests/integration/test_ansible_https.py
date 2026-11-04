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
from support import ROLE, grant, config, HASH, FakeAPI, flat_settings
from https_fixture import HTTPFixture
from matrix_support import MatrixAPI, rule


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
        self.dry_path = self.fixture.root / (self._testMethodName + "-dry.yml")
        self.dry_path.unlink(missing_ok=True)

    def tearDown(self):
        self.fixture.doc = self.original_doc
        self.fixture.write_config()

    def run_play(self, mode="dry", check=False, grants=None, deckhouse=False, context=None,
                 diff=False, inventory=None, export=None, inventory_file=None, config_extra=None,
                 expected_failure=False, play_host="localhost", inventory_source="localhost,", matrix=None,
                 output_only=False, extra_vars=None):
        cfg = config(deckhouse)
        cfg["mode"] = mode
        cfg["connection"]["kubeconfig"] = str(self.fixture.kubeconfig)
        cfg.update(config_extra or {})
        if context:
            cfg["connection"]["context"] = context
        variables = {
            "ansible_python_interpreter": sys.executable,
            "k8s_configuration_grants": grants if grants is not None else [grant()],
            "k8s_configuration_no_log": False,
            # External-user calculation tests explicitly retain their User columns.
            "k8s_configuration_matrix_include_external_users": True,
            "k8s_configuration_report_path": str(self.dry_path),
            "k8s_configuration_export_audit_destination": str(self.fixture.root / "export-audit.yml"),
        }
        variables.update(flat_settings(cfg, "k8s_configuration_config"))
        variables.update(flat_settings(dict({"destination": str(self.export_path)}, **(export or {})),
                                       "k8s_configuration_export"))
        if inventory is not None:
            variables.update(inventory)
        if matrix is not None:
            variables.update(flat_settings(matrix, "k8s_configuration_matrix"))
        play = [
            {
                "name": "HTTPS integration",
                "hosts": play_host,
                "gather_facts": False,
                "vars": variables,
                "roles": ["k8s-configuration"],
            }
        ]
        if output_only:
            play[0].pop("roles")
            play[0]["tasks"] = [{"ansible.builtin.include_role": {
                "name": "k8s-configuration", "tasks_from": "output",
            }}]
        if inventory_file:
            for key in ("grants",):
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
        cmd = ["ansible-playbook", "-i", inventory_source, "-c", "local", str(path)]
        for value in extra_vars or []:
            cmd.extend(["-e", value])
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

    def test_dry_after_apply_saves_empty_change_plan(self):
        self.run_play("apply")
        self.fixture.api.calls.clear()
        self.run_play("dry")
        report = yaml.safe_load(self.dry_path.read_text())
        self.assertEqual({key: report[key] for key in ("add", "change", "remove")},
                         {"add": [], "change": [], "remove": []})
        self.assertNotIn("planned", report)
        self.assertNotIn("changes", report)
        self.assertEqual(len(report["metadata"]["digest"]), 64)
        self.assertNotIn("before:", self.dry_path.read_text())
        self.assertNotIn("after:", self.dry_path.read_text())
        self.assertTrue(all(call[0] == "GET" for call in self.fixture.api.calls))

    def test_dry_file_contains_only_operations_and_changed_fields(self):
        self.run_play("apply", grants=[grant("old"), grant("updated")])
        self.fixture.api.calls.clear()
        updated = grant("updated", subjects=[{"kind": "User", "name": "alice"}])
        self.run_play("dry", grants=[updated, grant("new", scope={"cluster": True})],
                      inventory={"k8s_configuration_config_management_prune": True}, diff=True)
        text = self.dry_path.read_text()
        report = yaml.safe_load(text)
        self.assertEqual([len(report[key]) for key in ("add", "change", "remove")], [1, 1, 1])
        self.assertEqual(report["change"][0]["fields"], {"subjects": {
            "before": [{"kind": "Group", "name": "readers"}],
            "after": [{"kind": "User", "name": "alice"}],
        }})
        self.assertIn("roleRef: {kind: ClusterRole, name: view}", text)
        self.assertNotIn("namespace", report["add"][0])
        for redundant in ("privilege_change", "allow_collision", "adoption", "apiVersion", "apiGroup", "planned", "summary"):
            self.assertNotIn(redundant, text)
        self.assertTrue(all(call[0] == "GET" for call in self.fixture.api.calls))

    def test_context_does_not_redact_namespace(self):
        self.fixture.doc["contexts"][0]["name"] = "dev"
        self.fixture.doc["current-context"] = "dev"
        self.fixture.write_config()
        self.run_play("apply", context="dev")
        output = self.run_play("export", context="dev")
        self.assertIn("dev", self.export_path.read_text())
        self.assertNotIn("VALUE_SPECIFIED_IN_NO_LOG_PARAMETER", self.export_path.read_text())

    def test_deckhouse_ready_modules_without_moduleconfigs_or_deployment(self):
        api = self.fixture.api
        for name in ("user-authn", "user-authz"):
            api.objects.pop("/apis/deckhouse.io/v1alpha1/moduleconfigs/" + name)
        api.objects.pop("/apis/apps/v1/namespaces/d8-system/deployments/deckhouse")
        self.run_play("apply", deckhouse=True, grants=[], config_extra={"deckhouse": {}})
        self.assertIn("changed=0", self.run_play("apply", deckhouse=True, grants=[], config_extra={"deckhouse": {}}))
        self.run_play("export", deckhouse=True, config_extra={"deckhouse": {}})

    def test_flat_variables_override_settings(self):
        self.run_play("apply", inventory={
            "k8s_configuration_config_management_owner": "flat-owner",
            "k8s_configuration_config_safety_max_deletions": "{{ deletion_limit }}",
            "deletion_limit": 0,
        })
        bindings = [obj for obj in self.fixture.api.objects.values() if obj.get("kind") == "RoleBinding"]
        self.assertEqual(bindings[0]["metadata"]["labels"]["access-manager.ansible.local/owner"], "flat-owner")

    def test_manual_dkp_assigns_rights_without_managing_fixture_identities_or_roles(self):
        from support import INFO
        root = ROLE.parents[1] / "manual-test-dkp"
        api = self.fixture.api = FakeAPI()
        fixtures = list(yaml.safe_load_all((root / "manifests/fixtures.yml").read_text()))
        for doc in fixtures:
            if doc["kind"] in INFO:
                api.store(doc)
        api.store({"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRole",
                   "metadata": {"name": "admin"}, "rules": []})
        protected = {path: copy.deepcopy(obj) for path, obj in api.objects.items()
                     if obj.get("kind") in ("User", "Group", "Role", "ClusterRole")}
        variables = yaml.safe_load((root / "inventory/group_vars/access_test_dkp/k8s-config.yml").read_text())
        variables.update(manual_dkp_mode="apply", manual_dkp_kubeconfig=str(self.fixture.kubeconfig),
                         ansible_become=False,
                         k8s_configuration_report_path=str(self.dry_path))
        self.run_play("apply", inventory=variables, check=True)
        self.assertTrue(all(call[0] == "GET" for call in api.calls))
        output = self.run_play("apply", inventory=variables)
        bindings = [obj for obj in api.objects.values() if obj.get("kind") in ("RoleBinding", "ClusterRoleBinding")]
        expected = sum(len(g["scope"].get("namespaces", [""])) for g in variables["manual_dkp_grants_baseline"])
        self.assertEqual(len(bindings), expected)
        subjects = {(s["kind"], s["name"]) for obj in bindings for s in obj["subjects"]}
        self.assertIn(("User", "dkp-access-auditor@example.invalid"), subjects)
        self.assertIn(("Group", "dkp-access:readers"), subjects)
        self.assertIn(("User", "ldap-test-reader@example.invalid"), subjects)
        self.assertIn(("Group", "ldap:dkp-access:readers"), subjects)
        self.assertEqual(protected, {path: api.objects[path] for path in protected})
        self.assertIn("changed=0", self.run_play("apply", inventory=variables))
        self.assertFalse(any("subjectaccessreviews" in call[1] for call in api.calls))
        for doc in fixtures:
            if doc["kind"] == "User":
                self.assertNotIn(doc["spec"]["password"], output)

    def test_matrix_inventory_reads_roles_and_never_live_bindings(self):
        import csv
        api = self.fixture.api = MatrixAPI()
        api.role("view", [rule(["pods"], ["get", "list"])])
        secret = api.role("secret", [rule(["secrets"], ["get"])])
        api.bind("foreign", secret, [{"kind": "Group", "name": "foreign"}])
        api.calls.clear()
        def deny_bindings(method, path, body):
            if path.endswith(("/rolebindings", "/clusterrolebindings")):
                raise AssertionError("Live bindings must not be read for inventory matrix")
        api.fail = deny_bindings
        directory = self.fixture.root / "inventory-matrix"
        variables = {"k8s_configuration_users": "{{ undefined_password_must_not_be_evaluated }}",
                     "k8s_configuration_groups": "{{ undefined_groups_must_not_be_evaluated }}"}
        self.run_play("matrix", inventory=variables,
                      matrix={"source": "inventory", "output_dir": str(directory)}, check=True)
        self.assertFalse(directory.exists())
        self.run_play("matrix", inventory=variables,
                      matrix={"source": "inventory", "output_dir": str(directory)})
        self.assertEqual({path.name for path in directory.iterdir()},
                         {"matrix-inventory.csv", "bindings-inventory.csv", "subjects-inventory.csv"})
        with (directory / "matrix-inventory.csv").open() as stream:
            rows = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual({row["resource"] for row in rows}, {"pods"})
        self.assertEqual(rows[0]["Group:readers"], "GL......")
        self.assertNotIn("Group:foreign", rows[0])
        self.assertIn("inventory-rbac", (directory / "bindings-inventory.csv").read_text())
        self.assertIn("changed=0", self.run_play("matrix", inventory=variables,
                      matrix={"source": "inventory", "output_dir": str(directory)}))
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matrix_inventory_missing_role_does_not_write_reports(self):
        api = self.fixture.api = MatrixAPI()
        directory = self.fixture.root / "missing-inventory-role"
        missing = grant(roleRef={"kind": "ClusterRole", "name": "missing"})
        output = self.run_play("matrix", grants=[missing], matrix={"source": "inventory", "output_dir": str(directory)},
                               expected_failure=True)
        self.assertIn("Inventory matrix role does not exist", output)
        self.assertFalse(directory.exists())
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matrix_external_user_toggle_accepts_key_value_cli_booleans(self):
        import csv
        api = self.fixture.api = MatrixAPI()
        role = api.role("read", [rule(["pods"], ["get"])])
        api.bind("group", role, [{"kind": "Group", "name": "ldap:readers"}])
        api.bind("user", role, [{"kind": "User", "name": "ldap-test-auditor@example.invalid"}])
        auth = api.role("auth", [rule(["pods"], ["list"]), rule(["secrets"], ["get"])])
        api.bind("auth", auth, [{"kind": "Group", "name": "system:authenticated"}])
        directory = self.fixture.root / "cli-bool-matrix"
        for value, present in (("true", True), ("false", False)):
            with self.subTest(value=value):
                self.run_play("matrix", matrix={"output_dir": str(directory)},
                              extra_vars=["k8s_configuration_matrix_include_external_users=" + value])
                with (directory / "matrix.csv").open() as stream:
                    rows = list(csv.DictReader(stream, delimiter=";"))
                self.assertEqual(len(rows), 1)
                self.assertEqual("User:ldap-test-auditor@example.invalid" in rows[0], present)
                self.assertEqual(rows[0]["Group:ldap:readers"], "G.......")
                if present:
                    self.assertEqual(rows[0]["User:ldap-test-auditor@example.invalid"], "G.......")
                    with (directory / "subjects.csv").open() as stream:
                        subjects = list(csv.DictReader(stream, delimiter=";"))
                    external = next(r for r in subjects if r["kind"] == "User")
                    self.assertEqual(external["rights_basis"], "direct_only")
                    with (directory / "bindings.csv").open() as stream:
                        sources = list(csv.DictReader(stream, delimiter=";"))
                    self.assertEqual({r["origin"] for r in sources if r["subject"] == external["subject"]}, {"direct"})
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matrix_csv_check_idempotence_and_no_desired_password_evaluation(self):
        import csv
        import shutil
        api = self.fixture.api = MatrixAPI()
        role = api.role("audit-pods", [rule(["pods"], ["get", "list", "watch"])])
        api.bind("manual-audit", role, [{"kind": "Group", "name": "devs"}])
        directory = self.fixture.root / "matrix"
        if directory.exists():
            shutil.rmtree(directory)
        options = {"output_dir": str(directory), "memberships": [
            {"kind": "User", "name": "alice", "groups": ["devs"], "complete": True}
        ]}
        variables = {
            "k8s_configuration_users": "{{ undefined_password_must_not_be_evaluated }}",
            "k8s_configuration_matrix_filename": "rights.csv",
            "k8s_configuration_matrix_bindings_filename": "sources.csv",
            "k8s_configuration_matrix_subjects_filename": "people.csv",
        }
        self.run_play("matrix", matrix=options, inventory=variables, check=True, diff=True)
        self.assertFalse(directory.exists())
        self.run_play("matrix", matrix=options, inventory=variables, diff=True)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual({p.name for p in directory.iterdir()}, {"rights.csv", "sources.csv", "people.csv"})
        for path in directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with (directory / "rights.csv").open() as stream:
            row = next(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(row["User:alice"], "........")
        self.assertEqual(row["Group:devs"], "GLW.....")
        self.assertIn("manual-audit", (directory / "sources.csv").read_text())
        self.assertIn("changed=0", self.run_play("matrix", matrix=options, inventory=variables))
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_outputs_use_controller_even_with_unusable_target_connection(self):
        results = {
            "dry": {"plan": {"summary": {"create": 0}, "planned": {"add": [], "change": [], "remove": []}}},
            "export": {"exported": {"inventory": {"k8s_configuration_users": [{"password_hash": HASH}]},
                                    "warnings": []}},
            "matrix": {"matrix": {"files": {name: "namespace;subject\ndev;reader\n" for name in
                                             ("matrix.csv", "bindings.csv", "subjects.csv")}}},
        }
        for mode, result in results.items():
            with self.subTest(mode=mode):
                root = self.fixture.root / ("controller-" + mode)
                variables = {
                    "ansible_connection": "ssh", "ansible_host": "127.0.0.1", "ansible_port": 1,
                    "ansible_python_interpreter": "/missing/target/python",
                    "ansible_become": True, "ansible_become_exe": "/bin/false",
                    "k8s_configuration_result": result,
                    "k8s_configuration_report_path": str(root / "plan.yml"),
                    "k8s_configuration_export_destination": str(root / "inventory.yml"),
                    "k8s_configuration_export_audit_destination": str(root / "audit.yml"),
                    "k8s_configuration_matrix_output_dir": str(root),
                }
                output = self.run_play(mode, inventory=variables, play_host="executor",
                                       inventory_source="executor,", output_only=True)
                self.assertIn("executor -> localhost", output)
                self.assertEqual(len(list(root.iterdir())), {"dry": 1, "export": 2, "matrix": 3}[mode])
                for path in root.iterdir():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.fixture.api.calls)

    def test_dry_controller_report_relative_path_check_and_idempotence(self):
        root = self.fixture.root / "controller-dry-relative"
        relative = "controller-dry-relative/plan.yml"
        variables = {"k8s_configuration_report_path": relative}
        self.run_play("dry", inventory=variables, check=True, play_host="executor", inventory_source="executor,")
        self.assertFalse(root.exists())
        root.mkdir(mode=0o755)
        root.chmod(0o755)
        output = self.run_play("dry", inventory=variables, play_host="executor", inventory_source="executor,")
        self.assertIn("executor -> localhost", output)
        self.assertEqual(root.stat().st_mode & 0o777, 0o755)
        data = yaml.safe_load((root / "plan.yml").read_text())
        self.assertEqual(len(data["add"]), 1)
        self.assertIn("changed=0", self.run_play("dry", inventory=variables,
                                               play_host="executor", inventory_source="executor,"))
        self.assertTrue(all(call[0] == "GET" for call in self.fixture.api.calls))

    def test_matrix_deckhouse_has_no_hashes_and_no_readiness_dependency(self):
        api = self.fixture.api = MatrixAPI()
        api.omit_type_meta = True
        api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "jane"},
                   "spec": {"email": "jane@example.org", "password": HASH}})
        api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group", "metadata": {"name": "devs"},
                   "spec": {"name": "developers", "members": [{"kind": "User", "name": "jane"}]}})
        role = api.role("audit-pods", [rule(["pods"], ["get"])])
        api.bind("derived", role, [{"kind": "Group", "name": "developers"}])
        empty_role = api.role("empty-system-role", None)
        api.bind("empty-system-binding", empty_role, [{"kind": "Group", "name": "developers"}],
                 ownerReferences=None)
        api.objects.pop("/apis/apps/v1/namespaces/d8-system/deployments/deckhouse")
        directory = self.fixture.root / "matrix-dkp"
        # Use the real scenario without creating its manual-test namespaces.
        scenario = ROLE.parents[1] / "manual-test-dkp/scenarios/matrix.yml"
        options = yaml.safe_load(scenario.read_text())
        options["k8s_configuration_matrix_output_dir"] = str(directory)
        self.run_play("matrix", deckhouse=True, inventory=options,
                      config_extra={"deckhouse": {}}, diff=True)
        for path in directory.iterdir():
            self.assertNotIn(HASH, path.read_text())
            self.assertNotIn(self.fixture.secret, path.read_text())
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matrix_uses_live_local_memberships_and_external_groups_without_inventory_dictionary(self):
        import csv
        api = self.fixture.api = MatrixAPI()
        api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "local"},
                   "spec": {"email": "local@example.org", "password": HASH}})
        group = api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group", "metadata": {"name": "local-team"},
                           "spec": {"name": "local:readers", "members": [{"kind": "User", "name": "local"}]}})
        role = api.role("pods", [rule(["pods"], ["get"])])
        api.bind("local-read", role, [{"kind": "Group", "name": "local:readers"}])
        api.bind("ldap-read", role, [{"kind": "Group", "name": "ldap:readers"}])
        secret = api.role("direct-ldap", [rule(["secrets"], ["get"])])
        api.bind("direct-ldap", secret, [{"kind": "User", "name": "ldap@example.org"}])
        directory = self.fixture.root / "local-auto-matrix"
        variables = {"k8s_configuration_matrix_include_external_users": False}
        options = {"output_dir": str(directory)}
        self.run_play("matrix", deckhouse=True, matrix=options, inventory=variables)
        def read_rows():
            with (directory / "matrix.csv").open() as stream:
                return list(csv.DictReader(stream, delimiter=";"))
        rows = read_rows()
        self.assertEqual({r["resource"] for r in rows}, {"pods"})
        self.assertEqual(rows[0]["User:local@example.org"], "g.......")
        self.assertEqual(rows[0]["Group:ldap:readers"], "G.......")
        self.assertNotIn("User:ldap@example.org", rows[0])
        group["spec"]["members"] = []
        api.store(group)
        self.run_play("matrix", deckhouse=True, matrix=options, inventory=variables)
        self.assertEqual(read_rows()[0]["User:local@example.org"], "........")
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matrix_flat_filters_on_controller_preserve_hidden_group_grants(self):
        import csv
        api = self.fixture.api = MatrixAPI()
        api.store({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "kube-system"}})
        role = api.role("global-read", [rule(["pods"], ["get"])])
        api.bind("authenticated", role, [{"kind": "Group", "name": "system:authenticated"}], namespace="")
        for name in ("alice", "bob"):
            api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": name},
                       "spec": {"email": name + "@example.org"}})
        directory = self.fixture.root / "filtered-matrix"
        variables = {
            "k8s_configuration_matrix_namespace_mode": "system",
            "k8s_configuration_matrix_namespace_include": ["kube-*"],
            "k8s_configuration_matrix_namespace_exclude": ["kube-public"],
            "k8s_configuration_matrix_users_include": ["*@example.org"],
            "k8s_configuration_matrix_users_exclude": ["bob*"],
            "k8s_configuration_matrix_groups_exclude": ["*"],
            "k8s_configuration_matrix_include_cluster_scoped": False,
            "k8s_configuration_matrix_memberships": [
                {"kind": "User", "name": name, "groups": [], "complete": True}
                for name in ("alice@example.org", "bob@example.org")],
        }
        self.run_play("matrix", deckhouse=True, matrix={"output_dir": str(directory)}, inventory=variables)
        with (directory / "matrix.csv").open() as stream:
            rows = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["namespace"], "kube-system")
        self.assertEqual(rows[0]["User:alice@example.org"], "g.......")
        self.assertNotIn("User:bob@example.org", rows[0])
        self.assertFalse(any(key.startswith("Group:") for key in rows[0]))
        self.assertIn("system:authenticated", (directory / "bindings.csv").read_text())
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matrix_broad_subject_filter_removes_columns_and_wildcard_rows(self):
        import csv
        api = self.fixture.api = MatrixAPI()
        for name, verbs in (("admins", ["*"]), ("auditors", ["get"])):
            role = api.role(name, [rule(["*"], verbs, group="*")])
            api.bind(name, role, [{"kind": "Group", "name": name}], namespace="")
        normal = api.role("normal", [rule(["pods"], ["get"])])
        api.bind("normal", normal, [{"kind": "User", "name": "alice"}])
        api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "bob"},
                   "spec": {"email": "bob"}})
        directory = self.fixture.root / "broad-matrix"
        options = {"output_dir": str(directory), "memberships": [
            {"kind": "User", "name": "bob", "groups": ["admins"], "complete": False}]}
        self.run_play("matrix", deckhouse=True, matrix=options)
        with (directory / "matrix.csv").open() as stream:
            rows = list(csv.DictReader(stream, delimiter=";"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resource"], "pods")
        self.assertEqual(rows[0]["User:alice"], "G.......")
        self.assertNotIn("User:bob", rows[0])
        self.assertNotIn("Group:admins", rows[0])
        self.assertNotIn("Group:auditors", rows[0])
        self.run_play("matrix", deckhouse=True, matrix=options,
                      inventory={"k8s_configuration_matrix_exclude_broad_subjects": False})
        with (directory / "matrix.csv").open() as stream:
            full = list(csv.DictReader(stream, delimiter=";"))
        self.assertGreater(len(full), len(rows))
        self.assertIn("User:bob", full[0])
        self.assertTrue(all(call[0] == "GET" for call in api.calls))

    def test_matrix_forbidden_fails_before_creating_reports(self):
        from access_manager.client import APIError
        api = self.fixture.api = MatrixAPI()
        def deny(method, path, body):
            if path.endswith("/rolebindings"):
                raise APIError(method, 403)
        api.fail = deny
        directory = self.fixture.root / "matrix-forbidden"
        output = self.run_play("matrix", matrix={"output_dir": str(directory)}, expected_failure=True)
        self.assertIn("HTTP 403", output)
        self.assertFalse(directory.exists())

    def test_matrix_unexpected_failure_reports_safe_code_location(self):
        api = self.fixture.api = MatrixAPI()
        role = api.role("malformed-rule", [None])
        api.bind("malformed-rule", role, [{"kind": "Group", "name": "developers"}])
        directory = self.fixture.root / "matrix-unexpected"
        output = self.run_play("matrix", matrix={"output_dir": str(directory)}, expected_failure=True)
        self.assertIn("TypeError at matrix.py:", output)
        self.assertNotIn("Traceback", output)
        self.assertFalse(directory.exists())

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
        self.assertTrue(self.dry_path.exists())
        self.assertTrue(all(c[0] == "GET" for c in api.calls))
        output = self.run_play("apply")
        self.assertIn("changed=1", output)
        output = self.run_play("apply")
        self.assertIn("changed=0", output)
        api.calls = []
        self.run_play("export")
        self.assertTrue(all(c[0] == "GET" for c in api.calls))

    def test_deckhouse_apply_does_not_manage_users_or_groups(self):
        api = self.fixture.api
        identities = {}
        for kind, version, name, spec in (
                ("User", "v1", "jane", {"email": "jane@example.org", "password": HASH}),
                ("Group", "v1alpha1", "devs", {"name": "developers", "members": []})):
            obj = api.store({"apiVersion": "deckhouse.io/" + version, "kind": kind,
                             "metadata": {"name": name}, "spec": spec})
            identities[(kind, name)] = copy.deepcopy(obj)
        self.assertIn("changed=0", self.run_play("apply", grants=[], deckhouse=True))
        for obj in api.objects.values():
            key = (obj.get("kind"), obj.get("metadata", {}).get("name"))
            if key in identities:
                self.assertEqual(obj, identities[key])
        self.assertTrue(all("/users" not in call[1] and "/groups" not in call[1]
                            for call in api.calls))

    def test_default_export_is_compact_assignments_only_and_importable(self):
        grant_spec = grant(subjects=[{"kind": "User", "name": "jane@example.org"}])
        self.run_play("apply", deckhouse=True, grants=[grant_spec])
        self.run_play("export", deckhouse=True)
        text = self.export_path.read_text()
        data = yaml.safe_load(text)
        self.assertEqual(set(data), {"k8s_configuration_grants"})
        self.assertEqual(data["k8s_configuration_grants"][0]["subjects"],
                         [{"kind": "User", "name": "jane@example.org"}])
        self.assertIn("roleRef: {kind: ClusterRole, name: view}", text)
        self.assertIn("scope: {namespaces: [dev]}", text)
        self.assertIn("- {kind: User, name: jane@example.org}", text)
        self.assertNotIn(HASH, text)
        self.fixture.api = FakeAPI()
        self.assertIn("changed=1", self.run_play("apply", inventory_file=self.export_path))
        self.assertIn("changed=0", self.run_play("apply", inventory_file=self.export_path))

    def test_export_omits_standalone_users_groups_and_hashes(self):
        self.run_play("apply", grants=[], deckhouse=True)
        self.fixture.api.calls = []
        self.run_play("export", deckhouse=True, diff=True)
        self.assertTrue(all(c[0] == "GET" for c in self.fixture.api.calls))
        data = yaml.safe_load(self.export_path.read_text())
        self.assertEqual(data, {"k8s_configuration_grants": []})
        self.assertEqual(self.export_path.stat().st_mode & 0o777, 0o600)
        audit = (self.fixture.root / "export-audit.yml").read_text()
        self.assertNotIn(HASH, audit)
        self.assertNotIn("password", audit)

    def test_export_check_stays_export_and_previews_file_without_writing(self):
        self.run_play("apply")
        self.fixture.api.calls = []
        output = self.run_play("export", check=True)
        self.assertRegex(output, r"changed=[1-9]")
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
            self.assertTrue(self.dry_path.exists())
            self.assertTrue(all(c[0] == "GET" for c in self.fixture.api.calls))

    def test_apply_diff_with_default_no_log_is_rendered_and_sanitized(self):
        output = self.run_play("apply", diff=True, inventory={"k8s_configuration_no_log": True})
        self.assertIn("--- before: RoleBinding/", output)
        self.assertIn("+++ after: RoleBinding/", output)
        self.assertIn("changed=1", output)

    def test_incomplete_export_fails_with_public_reason_and_writes_no_file(self):
        grant_spec = {"id": "native", "backend": "deckhouse", "accessLevel": "User",
                      "subjects": [{"kind": "Group", "name": "readers"}],
                      "scope": {"namespaces": ["dev"]}}
        self.run_play("apply", deckhouse=True, grants=[grant_spec])
        obj = next(o for o in self.fixture.api.objects.values() if o.get("kind") == "AuthorizationRule")
        obj["spec"]["additionalRoles"] = [{"name": "cluster-admin"}]
        output = self.run_play("export", deckhouse=True, expected_failure=True)
        self.assertIn("unsupported access assignments", output)
        self.assertFalse(self.export_path.exists())

    def test_remote_inventory_host_uses_its_own_kubectl_configuration(self):
        # Local transport substitutes for SSH; inventory target remains a named host.
        self.run_play("apply", play_host="executor", inventory_source="executor,")
        self.assertIn("changed=0", self.run_play(
            "apply", play_host="executor", inventory_source="executor,"
        ))

    def test_kubectl_patch_and_delete_preserve_concurrency_preconditions(self):
        desired = grant(target_name="legacy:readers")
        self.run_play("apply", grants=[desired])
        updated = copy.deepcopy(desired)
        updated["subjects"][0]["name"] = "updated-readers"
        self.fixture.api.calls = []
        self.run_play("apply", grants=[updated], config_extra={"server_validation": True})
        patches = [call for call in self.fixture.api.calls if call[0] == "PATCH"]
        self.assertEqual(len(patches), 2)  # server dry-run and actual update
        self.assertEqual(patches[0][3]["dryRun"], "All")
        for call in patches:
            self.assertIn({"op": "test", "path": "/metadata/uid",
                           "value": call[2][0]["value"]}, call[2])
            self.assertEqual(call[2][1]["path"], "/metadata/resourceVersion")
        self.assertIn("changed=0", self.run_play("apply", grants=[updated]))
        self.fixture.api.calls = []
        self.run_play("apply", grants=[dict(updated, state="absent")])
        deletes = [call for call in self.fixture.api.calls if call[0] == "DELETE"]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(set(deletes[0][2]["preconditions"]), {"uid", "resourceVersion"})
        self.assertFalse(any(o.get("kind") == "RoleBinding" for o in self.fixture.api.objects.values()))


if __name__ == "__main__":
    unittest.main()
