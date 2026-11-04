import csv
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import config, grant
from matrix_support import MatrixAPI, rule
from access_manager.matrix import Matrix
from access_manager.schema import AccessError


def rows(report, filename="matrix.csv"):
    return list(csv.DictReader(io.StringIO(report["files"][filename]), delimiter=";"))


class InventoryMatrixTests(unittest.TestCase):
    def setUp(self):
        self.api = MatrixAPI()
        self.cfg = config(mode="matrix")
        self.role = self.api.role("view", [rule(["pods"], ["get", "list"])])

    def report(self, grants, **options):
        return Matrix(self.api, self.cfg, dict(source="inventory", **options), grants=grants).report()

    def test_live_bindings_are_not_read_or_used_and_current_rules_are_used(self):
        secret = self.api.role("secret", [rule(["secrets"], ["get"])])
        self.api.bind("foreign", secret, [{"kind": "Group", "name": "foreign"}])
        self.api.calls.clear()
        def deny_bindings(method, path, body):
            if path.endswith(("/rolebindings", "/clusterrolebindings")):
                self.fail("Inventory mode must not read live bindings")
        self.api.fail = deny_bindings
        report = self.report([grant()])
        self.assertEqual(report["summary"]["source"], "inventory")
        self.assertEqual({row["resource"] for row in rows(report)}, {"pods"})
        self.assertEqual(rows(report)[0]["Group:readers"], "GL......")
        self.assertNotIn("foreign", report["files"]["subjects.csv"])
        self.assertEqual({row["record_type"] for row in rows(report, "bindings.csv")}, {"inventory-rbac"})
        self.assertIn("inventory-binding", report["files"]["subjects.csv"])
        self.role["rules"] = [rule(["pods"], ["delete"])]
        self.api.store(self.role)
        self.assertEqual(rows(self.report([grant()]))[0]["Group:readers"], "......D.")
        self.assertTrue(all(call[0] == "GET" for call in self.api.calls))

    def test_role_namespace_cluster_scope_and_absent_entries(self):
        self.api.role("local", [rule(["configmaps"], ["get"])], namespace="dev")
        grants = [grant("local", roleRef={"kind": "Role", "name": "local"}),
                  grant("cluster", scope={"cluster": True}),
                  {"id": "absent", "backend": "rbac", "scope": {"namespaces": ["dev"]}, "state": "absent"}]
        report = self.report(grants)
        self.assertTrue(any(row["resource"] == "configmaps" and row["namespace"] == "dev" for row in rows(report)))
        self.assertTrue(any(row["resource"] == "pods" and row["namespace"] == "test" for row in rows(report)))
        self.assertNotIn("am-absent-", report["files"]["bindings.csv"])
        sources = rows(report, "bindings.csv")
        self.assertEqual({row["binding_kind"] for row in sources}, {"RoleBinding", "ClusterRoleBinding"})
        self.assertEqual(rows(self.report([])), [])

    def test_missing_inputs_namespace_role_and_native_backend_fail_clearly(self):
        with self.assertRaisesRegex(AccessError, "requires k8s_configuration_grants"):
            Matrix(self.api, self.cfg, {"source": "inventory"})
        for grants, message in (([grant(roleRef={"kind": "ClusterRole", "name": "missing"})], "role does not exist"),
                                ([grant(scope={"namespaces": ["missing"]})], "namespace does not exist")):
            with self.subTest(grants=grants), self.assertRaisesRegex(AccessError, message):
                self.report(grants)
        cfg = config(True, mode="matrix")
        native = {"id": "native", "backend": "deckhouse", "accessLevel": "User",
                  "subjects": [{"kind": "Group", "name": "readers"}], "scope": {"namespaces": ["dev"]}}
        with self.assertRaisesRegex(AccessError, "supports backend: rbac only"):
            Matrix(self.api, cfg, {"source": "inventory"}, grants=[native])

    def test_live_local_membership_is_resolved_for_inventory_assignments(self):
        self.cfg = config(True, mode="matrix")
        self.api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "alice"},
                        "spec": {"email": "alice@example.org"}})
        group = self.api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group",
                                "metadata": {"name": "readers"}, "spec": {"name": "readers",
                                "members": [{"kind": "User", "name": "alice"}]}})
        self.assertEqual(rows(self.report([grant()]))[0]["User:alice@example.org"], "gl......")
        group["spec"]["members"] = []
        self.api.store(group)
        self.assertEqual(rows(self.report([grant()]))[0]["User:alice@example.org"], "........")
