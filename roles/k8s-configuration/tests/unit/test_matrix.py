import csv
import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import config, HASH
from matrix_support import MatrixAPI, rule
from access_manager.client import APIError
from access_manager.matrix import Matrix, validate_matrix
from access_manager.schema import AccessError, unexpected_error


def records(report, file="matrix.csv", delimiter=";"):
    return list(csv.DictReader(io.StringIO(report["files"][file]), delimiter=delimiter))


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.api = MatrixAPI()
        self.cfg = config(mode="matrix")

    def report(self, **options):
        # Tests of explicit external-user masks opt in; separate tests cover defaults.
        options.setdefault("include_external_users", True)
        return Matrix(self.api, self.cfg, options).report()

    def mask(self, report, subject, resource="pods", namespace="dev", name="", action="standard", group=""):
        rows = [r for r in records(report) if r["resource"] == resource and r["namespace"] == namespace
                and r["resource_name"] == name and r["action"] == action and r["api_group"] == group]
        self.assertEqual(len(rows), 1, rows)
        return rows[0][subject]

    def local_user(self, name="alice"):
        self.cfg = config(True, mode="matrix")
        self.api.store({"apiVersion": "deckhouse.io/v1", "kind": "User",
                        "metadata": {"name": name.split("@")[0]}, "spec": {"email": name}})

    def members(self, name="alice", groups=None, complete=True):
        return [{"kind": "User", "name": name, "groups": groups or [], "complete": complete}]

    def test_direct_inherited_union_and_every_source_are_preserved(self):
        self.local_user()
        read = self.api.role("read", [rule(["pods"], ["get", "list", "watch"])])
        edit = self.api.role("edit-pods", [rule(["pods"], ["get", "create", "update", "patch", "delete"])])
        self.api.bind("direct", read, [{"kind": "User", "name": "alice"}])
        self.api.bind("via-devs", edit, [{"kind": "Group", "name": "devs"}])
        result = self.report(memberships=self.members(groups=["devs"]))
        self.assertEqual(self.mask(result, "User:alice"), "GLWcupd.")
        self.assertEqual(self.mask(result, "Group:devs"), "G..CUPD.")
        audit = [r for r in records(result, "bindings.csv") if r["subject"] == "User:alice"]
        self.assertEqual({r["binding_name"] for r in audit}, {"direct", "via-devs"})
        self.assertEqual({r["origin"] for r in audit}, {"direct", "inherited"})
        self.assertTrue(all(call[0] == "GET" for call in self.api.calls))

    def test_list_items_without_kind_or_api_version(self):
        role = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.bind("direct", role, [{"kind": "User", "name": "alice"}])
        expected = self.report(memberships=self.members())
        self.api.omit_type_meta = True
        self.assertEqual(self.report(memberships=self.members()), expected)

    def test_null_optional_lists_are_empty_without_losing_grants(self):
        empty_role = self.api.role("empty", None)
        self.api.bind("empty-role", empty_role, [{"kind": "User", "name": "alice"}])
        self.api.bind("empty-binding", empty_role, None, ownerReferences=None)
        core = self.api.role("read", [rule(["pods"], ["get"], resourceNames=None, nonResourceURLs=None)])
        self.api.bind("read", core, [{"kind": "User", "name": "alice"}], ownerReferences=None)
        urls = self.api.role("urls", [{"verbs": ["get"], "apiGroups": None, "resources": None,
                                       "resourceNames": None, "nonResourceURLs": ["/metrics"]}])
        self.api.bind("urls", urls, [{"kind": "User", "name": "alice"}], namespace="")
        result = self.report(memberships=self.members())
        self.assertEqual(self.mask(result, "User:alice"), "G.......")
        self.assertTrue(any(r["non_resource_url"] == "/metrics" for r in records(result)))
        self.assertTrue(all(call[0] == "GET" for call in self.api.calls))

    def test_null_deckhouse_group_members(self):
        self.cfg = config(True, mode="matrix")
        self.api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group",
                        "metadata": {"name": "empty"}, "spec": {"name": "empty", "members": None}})
        self.api.omit_type_meta = True
        result = self.report()
        self.assertIn("Group:empty", result["files"]["subjects.csv"])

    def test_unexpected_error_diagnostic_contains_code_location_not_secrets(self):
        role = self.api.role("malformed", [None])
        self.api.bind("malformed", role, [{"kind": "User", "name": "alice"}])
        try:
            self.report()
        except TypeError as exc:
            diagnostic = unexpected_error(exc)
        else:
            self.fail("Expected malformed rule to raise TypeError")
        self.assertIn("TypeError at matrix.py:", diagnostic)
        try:
            raise RuntimeError("secret-token-should-not-be-printed")
        except RuntimeError as exc:
            self.assertNotIn("secret-token", unexpected_error(exc))

    def test_external_users_ignore_membership_completeness(self):
        read = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.bind("direct", read, [{"kind": "User", "name": "alice"}])
        self.assertEqual(self.mask(self.report(), "User:alice"), "G.......")
        self.assertEqual(self.mask(self.report(memberships=self.members()), "User:alice"), "G.......")
        self.assertEqual(self.mask(self.report(memberships=self.members(complete=False)), "User:alice"), "G.......")

    def test_missing_namespace_error_names_missing_filters(self):
        with self.assertRaisesRegex(AccessError, r"Unknown matrix namespace\(s\): missing-a, missing-b"):
            self.report(namespaces=["dev", "missing-b", "missing-a"])
        self.assertEqual(self.report(namespaces=[])["summary"]["rows"], 0)

    def test_serviceaccount_system_groups_and_user_alias(self):
        read = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.store({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "bot", "namespace": "test"}})
        self.api.bind("sa-group", read, [{"kind": "Group", "name": "system:serviceaccounts:test"}])
        self.api.bind("sa-alias", read, [{"kind": "User", "name": "system:serviceaccount:test:bot"}], namespace="test")
        result = self.report(subjects={"service_accounts": True})
        self.assertEqual(self.mask(result, "ServiceAccount:test/bot"), "g.......")
        self.assertEqual(self.mask(result, "ServiceAccount:test/bot", namespace="test"), "G.......")
        sa = next(r for r in records(result, "subjects.csv") if r["subject"] == "ServiceAccount:test/bot")
        self.assertTrue(set(json.loads(sa["groups"])) >= {"system:authenticated", "system:serviceaccounts", "system:serviceaccounts:test"})
        self.assertEqual(sa["membership_complete"], "true")

    def test_authenticated_and_anonymous_group_membership(self):
        self.local_user()
        read = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.bind("auth", read, [{"kind": "Group", "name": "system:authenticated"}])
        result = self.report(include_system_subjects=True, memberships=self.members() + self.members("system:anonymous"))
        self.assertEqual(self.mask(result, "User:alice"), "g.......")
        self.assertEqual(self.mask(result, "User:system:anonymous"), "........")

    def test_resource_names_and_broader_rules_project_to_named_rows(self):
        self.local_user()
        broad = self.api.role("broad", [rule(["configmaps"], ["list"])])
        named = self.api.role("named", [rule(["configmaps"], ["get", "create", "list", "watch", "deletecollection"], resourceNames=["public-config"])])
        self.api.bind("broad", broad, [{"kind": "User", "name": "alice"}])
        self.api.bind("named", named, [{"kind": "Group", "name": "devs"}])
        result = self.report(memberships=self.members(groups=["devs"]))
        self.assertEqual(self.mask(result, "User:alice", resource="configmaps", name="public-config"), "gLw.....")
        self.assertEqual(self.mask(result, "User:alice", resource="configmaps"), ".L......")

    def test_wildcards_subresources_and_custom_verbs(self):
        self.local_user()
        all_role = self.api.role("all", [rule(["*"], ["*"], group="*")])
        scale = self.api.role("scale", [rule(["*/scale"], ["patch"], group="apps")])
        special = self.api.role("special", [rule(["roles"], ["bind", "escalate"], group="rbac.authorization.k8s.io")])
        self.api.bind("all", all_role, [{"kind": "Group", "name": "admins"}], namespace="")
        self.api.bind("scale", scale, [{"kind": "User", "name": "alice"}])
        self.api.bind("special", special, [{"kind": "Group", "name": "admins"}])
        result = self.report(exclude_broad_subjects=False, memberships=self.members(groups=["admins"]))
        self.assertEqual(self.mask(result, "User:alice", resource="deployments/scale", group="apps"), "glwcuPdx")
        self.assertEqual(self.mask(result, "User:alice", resource="pods/exec"), "glwcupdx")
        self.assertEqual(self.mask(result, "Group:admins", resource="nodes", namespace="<cluster>"), "GLWCUPDX")
        self.assertEqual(self.mask(result, "User:alice", resource="roles", group="rbac.authorization.k8s.io", action="bind"), "y")
        self.assertTrue(any(r["resource"] == "*" and r["api_group"] == "*" for r in records(result)))

    def test_rolebinding_does_not_grant_cluster_resources_or_nonresource_urls(self):
        role = self.api.role("mixed", [rule(["nodes", "pods"], ["get"]), {"nonResourceURLs": ["/metrics"], "verbs": ["get"]}])
        self.api.bind("namespaced", role, [{"kind": "User", "name": "alice"}])
        rows = records(self.report())
        self.assertTrue(rows)
        self.assertTrue(all(r["resource"] == "pods" and r["namespace"] == "dev" for r in rows))

    def test_namespace_filter_keeps_cluster_bindings_namespaced_permissions(self):
        role = self.api.role("mixed", [rule(["nodes", "pods"], ["get"])])
        self.api.bind("global", role, [{"kind": "User", "name": "alice"}], namespace="")
        result = self.report(namespaces=["test"], include_cluster_scoped=False, memberships=self.members())
        self.assertEqual(self.mask(result, "User:alice", namespace="test"), "G.......")
        self.assertTrue(all(r["namespace"] == "test" and r["resource"] == "pods" for r in records(result)))

    def test_nonresource_url_prefix_union(self):
        self.local_user()
        broad = self.api.role("health", [{"nonResourceURLs": ["/healthz/*"], "verbs": ["get"]}])
        narrow = self.api.role("health-ready", [{"nonResourceURLs": ["/healthz/ready"], "verbs": ["get"]}])
        self.api.bind("health", broad, [{"kind": "Group", "name": "devs"}], namespace="")
        self.api.bind("ready", narrow, [{"kind": "User", "name": "alice"}], namespace="")
        result = self.report(memberships=self.members(groups=["devs"]))
        rows = {r["non_resource_url"]: r for r in records(result)}
        self.assertEqual(rows["/healthz/ready"]["User:alice"], "G.......")
        self.assertEqual(rows["/healthz/*"]["User:alice"], "g.......")

    def test_aggregated_role_uses_observed_rules_not_future_union(self):
        role = self.api.role("aggregated", [rule(["pods"], ["get"])],
                             aggregationRule={"clusterRoleSelectors": [{"matchLabels": {"aggregate": "yes"}}]})
        self.api.role("not-reconciled-yet", [rule(["secrets"], ["get"])])
        self.api.bind("aggregated", role, [{"kind": "User", "name": "alice"}])
        result = self.report()
        self.assertFalse(any(r["resource"] == "secrets" for r in records(result)))
        self.assertIn("clusterRoleSelectors", records(result, "bindings.csv")[0]["aggregation"])

    def test_managed_scope_is_explicitly_partial(self):
        role = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.bind("own", role, [{"kind": "User", "name": "alice"}], labels={
            "access-manager.ansible.local/owner": "test", "access-manager.ansible.local/managed-by": "ansible"})
        self.api.bind("foreign", role, [{"kind": "User", "name": "bob"}])
        result = self.report(scope="managed")
        self.assertEqual(result["summary"]["scope"], "managed")
        self.assertNotIn("User:bob", result["files"]["matrix.csv"])

    def test_deckhouse_membership_nested_groups_and_declarations_are_not_permissions(self):
        self.cfg = config(True, mode="matrix")
        self.api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "alice-local"},
                        "spec": {"email": "alice@example.org", "password": HASH}})
        for name, claim, members in (("inner", "team", [{"kind": "User", "name": "alice-local"}]),
                                     ("outer", "org", [{"kind": "Group", "name": "inner"}])):
            self.api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group", "metadata": {"name": name},
                            "spec": {"name": claim, "members": members}})
        car = self.api.store({"apiVersion": "deckhouse.io/v1", "kind": "ClusterAuthorizationRule",
                              "metadata": {"name": "org-view"}, "spec": {"accessLevel": "User",
                              "subjects": [{"kind": "Group", "name": "org"}],
                              "namespaceSelector": {"labelSelector": {"matchLabels": {"env": "review"}}}}})
        role = self.api.role("derived", [rule(["pods"], ["get"])])
        self.api.bind("derived", role, [{"kind": "Group", "name": "org"}], ownerReferences=[{
            "uid": car["metadata"]["uid"], "kind": car["kind"], "name": "org-view", "apiVersion": car["apiVersion"]}])
        result = self.report()
        self.assertEqual(self.mask(result, "User:alice@example.org"), "g.......")
        self.assertEqual(self.mask(result, "Group:team"), "g.......")
        declaration = next(r for r in records(result, "bindings.csv") if r["record_type"] == "deckhouse-declaration")
        self.assertEqual(json.loads(declaration["resolved_namespaces"]), ["dev", "test"])
        self.assertEqual(declaration["reconciliation"], "linked-by-owner-uid")
        self.assertFalse(any(r["namespace"] == "test" for r in records(result)))
        self.assertNotIn(HASH, compact_report(result))
        self.assertNotIn("/apis/apps/v1/namespaces/d8-system/deployments/deckhouse", [c[1] for c in self.api.calls])

    def test_deckhouse_cycle_and_unresolved_members_fail(self):
        self.cfg = config(True, mode="matrix")
        group = {"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group", "metadata": {"name": "loop"},
                 "spec": {"name": "loop", "members": [{"kind": "Group", "name": "loop"}]}}
        self.api.store(group)
        with self.assertRaisesRegex(AccessError, "Cyclic"):
            self.report()
        group["spec"]["members"] = [{"kind": "User", "name": "missing"}]
        self.api.store(group)
        with self.assertRaisesRegex(AccessError, "Unresolved"):
            self.report()

    def test_no_guessing_deckhouse_reconciliation_or_permissions(self):
        self.cfg = config(True, mode="matrix")
        self.api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "AuthorizationRule",
                        "metadata": {"name": "not-reconciled", "namespace": "dev"},
                        "spec": {"accessLevel": "Admin", "subjects": [{"kind": "User", "name": "alice"}]}})
        result = self.report()
        self.assertEqual(result["summary"]["rows"], 0)
        self.assertEqual(records(result, "bindings.csv")[0]["reconciliation"], "unverified")

    def test_explicit_membership_overrides_deckhouse_when_complete(self):
        self.cfg = config(True, mode="matrix")
        self.api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "alice"},
                        "spec": {"email": "alice@example.org"}})
        self.api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group", "metadata": {"name": "devs"},
                        "spec": {"name": "devs", "members": [{"kind": "User", "name": "alice"}]}})
        role = self.api.role("devs-read", [rule(["pods"], ["get"])])
        self.api.bind("read", role, [{"kind": "Group", "name": "devs"}])
        result = self.report(memberships=self.members("alice@example.org"))
        self.assertEqual(self.mask(result, "User:alice@example.org"), "........")

    def test_linked_declaration_scope_or_subject_drift_is_flagged(self):
        self.cfg = config(True, mode="matrix")
        declaration = self.api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "AuthorizationRule",
                                     "metadata": {"name": "stale", "namespace": "dev"},
                                     "spec": {"accessLevel": "User", "subjects": [{"kind": "User", "name": "alice"}]}})
        role = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.bind("stale-binding", role, [{"kind": "User", "name": "bob"}], namespace="test",
                      ownerReferences=[{"uid": declaration["metadata"]["uid"]}])
        result = self.report()
        audit = next(r for r in records(result, "bindings.csv") if r["record_type"] == "deckhouse-declaration")
        self.assertEqual(audit["reconciliation"], "linked-scope-or-subject-mismatch")
        self.assertEqual(self.mask(result, "User:bob", namespace="test"), "G.......")

    def test_pagination_unavailable_resources_and_literal_resource_name_star(self):
        self.api.page_size = 1
        role = self.api.role("future", [rule(["future"], ["get"], group="future.example.org"),
                                        rule(["configmaps"], ["get"], resourceNames=["*"])])
        self.api.bind("future", role, [{"kind": "User", "name": "alice"}], namespace="")
        result = self.report(memberships=self.members())
        self.assertEqual(self.mask(result, "User:alice", resource="future", namespace="<unknown>", group="future.example.org"), "G.......")
        self.assertEqual(self.mask(result, "User:alice", resource="configmaps", name="*"), "G.......")
        self.assertTrue(any("absent from discovery" in warning for warning in result["warnings"]))

    def test_fail_closed_on_missing_role_and_forbidden_reads(self):
        role = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.bind("broken", role, [{"kind": "User", "name": "alice"}])
        del self.api.objects[self.api.object_path(role)]
        with self.assertRaisesRegex(AccessError, "Dangling"):
            self.report()
        def forbidden(method, path, body):
            if path.endswith("/rolebindings"):
                raise APIError(method, 403)
        self.api.fail = forbidden
        with self.assertRaises(APIError):
            self.report()

    def test_deterministic_csv_quoting_formula_safety_and_filters(self):
        role = self.api.role("read", [rule(["pods"], ["get"], resourceNames=["=danger;\nvalue"])])
        self.api.bind("read", role, [{"kind": "User", "name": "alice"}])
        options = {"csv": {"delimiter": ","}, "subjects": {"groups": False, "service_accounts": False}}
        first = self.report(**options)
        self.api.objects = dict(reversed(list(self.api.objects.items())))
        self.assertEqual(first, self.report(**options))
        rows = records(first, delimiter=",")
        self.assertEqual(rows[0]["resource_name"], "'=danger;\nvalue")
        self.assertNotIn("Group:", first["files"]["matrix.csv"])

    def add_namespace(self, name):
        self.api.store({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name}})

    def test_default_filters_hide_system_and_sa_and_do_not_inherit_for_external_users(self):
        for ns in ("kube-system", "default", "d8-custom"):
            self.add_namespace(ns)
        role = self.api.role("global", [rule(["pods"], ["get"])])
        self.api.bind("system-group", role, [{"kind": "Group", "name": "system:authenticated"}], namespace="")
        self.api.bind("system-user", role, [{"kind": "User", "name": "system:controller"}], namespace="")
        self.api.bind("bot", role, [{"kind": "ServiceAccount", "name": "bot", "namespace": "dev"}])
        result = self.report(memberships=self.members())
        subjects = {r["subject"] for r in records(result, "subjects.csv")}
        self.assertEqual(subjects, {"User:alice"})
        self.assertEqual(records(result), [])
        self.assertNotIn("kube-system", {r["namespace"] for r in records(result)})
        sources = records(result, "bindings.csv")
        self.assertTrue(all(r["subject"] == "User:alice" for r in sources))
        self.assertTrue(all(r["via_group"] == "system:authenticated" for r in sources))
        self.assertEqual(result["summary"]["excluded_namespaces"], 1)
        self.assertGreaterEqual(result["summary"]["excluded_subjects"], 3)

    def test_system_namespace_mode_and_deckhouse_defaults_are_independent_of_subjects(self):
        self.cfg = config(True, mode="matrix")
        for ns in ("kube-system", "d8-system", "default"):
            self.add_namespace(ns)
        role = self.api.role("global", [rule(["pods", "nodes"], ["get"])])
        self.api.bind("global", role, [{"kind": "User", "name": "alice"}], namespace="")
        result = self.report(namespace_mode="system", include_cluster_scoped=False)
        self.assertEqual({r["namespace"] for r in records(result)}, {"kube-system", "d8-system", "d8-user-authn", "d8-user-authz"})
        self.assertEqual(self.mask(result, "User:alice", namespace="d8-system"), "G.......")
        result = self.report()
        self.assertNotIn("d8-system", {r["namespace"] for r in records(result)})
        result = self.report(system_namespaces=["kube-*"])
        self.assertIn("d8-system", {r["namespace"] for r in records(result)})
        result = self.report(namespace_mode="all")
        self.assertIn("d8-system", {r["namespace"] for r in records(result)})
        self.assertIn("<cluster>", {r["namespace"] for r in records(result)})

    def test_namespace_patterns_intersect_exact_list_and_exclusion_wins(self):
        for ns in ("project-a", "project-b", "other", "kube-system"):
            self.add_namespace(ns)
        role = self.api.role("global", [rule(["*"], ["get"], group="*")])
        self.api.bind("global", role, [{"kind": "User", "name": "alice"}], namespace="")
        result = self.report(exclude_broad_subjects=False, namespace_mode="all", namespaces=["project-a", "project-b", "other"],
                             namespace_include=["project-*"], namespace_exclude=["*-b"],
                             include_cluster_scoped=False)
        self.assertEqual({r["namespace"] for r in records(result)}, {"project-a"})
        empty = self.report(namespace_include=["absent-*"], include_cluster_scoped=False)
        self.assertEqual(records(empty), [])
        self.assertEqual(empty["summary"]["selected_namespaces"], [])

    def test_subject_patterns_exclusion_wins_and_hidden_custom_group_still_grants(self):
        self.local_user("alice@example.org")
        role = self.api.role("group", [rule(["pods"], ["get"])])
        self.api.bind("team", role, [{"kind": "Group", "name": "team-dev"}])
        self.api.bind("other", role, [{"kind": "User", "name": "bob@example.org"}])
        result = self.report(users_include=["*@example.org"], users_exclude=["bob*"],
                             groups_include=["team-*"], groups_exclude=["team-dev"],
                             memberships=self.members("alice@example.org", ["team-dev"]))
        self.assertEqual({r["subject"] for r in records(result, "subjects.csv")}, {"User:alice@example.org"})
        self.assertEqual(self.mask(result, "User:alice@example.org"), "g.......")
        self.assertEqual(records(result, "bindings.csv")[0]["via_group"], "team-dev")
        result = self.report(users_include=["nobody"], groups_include=["nobody"])
        self.assertEqual(records(result), [])
        self.assertEqual(result["summary"]["subjects"], 0)

    def test_custom_system_subject_patterns_can_be_overridden(self):
        role = self.api.role("direct", [rule(["pods"], ["get"])])
        for name in ("alice", "bot-ci", "system:controller"):
            self.api.bind(name, role, [{"kind": "User", "name": name}])
        result = self.report(system_subjects=["system:*", "bot-*"])
        self.assertEqual({r["subject"] for r in records(result, "subjects.csv")}, {"User:alice"})
        result = self.report(system_subjects=["system:*", "bot-*"], include_system_subjects=True,
                             users_include=["system:*", "bot-*"], users_exclude=["bot-ci"], subjects={"groups": False})
        self.assertEqual({r["subject"] for r in records(result, "subjects.csv")}, {"User:system:controller"})

    def test_serviceaccount_name_and_namespace_filters(self):
        role = self.api.role("global", [rule(["pods"], ["get"])])
        subjects = [{"kind": "ServiceAccount", "namespace": ns, "name": name}
                    for ns, name in (("dev", "bot"), ("dev", "skip"), ("test", "bot"))]
        self.api.bind("bots", role, subjects, namespace="")
        result = self.report(subjects={"service_accounts": True}, service_accounts_include=["*/bot"],
                             service_accounts_exclude=["test/*"], service_account_namespaces_include=["d*"],
                             service_account_namespaces_exclude=["unused"])
        self.assertEqual({r["subject"] for r in records(result, "subjects.csv")}, {"ServiceAccount:dev/bot"})
        self.assertEqual(self.mask(result, "ServiceAccount:dev/bot", namespace="test"), "G.......")

    def test_empty_rows_removed_after_subject_filter_but_unknowns_kept(self):
        self.local_user()
        role = self.api.role("hidden", [rule(["secrets"], ["get"])])
        self.api.bind("hidden", role, [{"kind": "User", "name": "system:controller"}])
        result = self.report(memberships=self.members())
        self.assertEqual(records(result), [])
        self.assertEqual(result["summary"]["omitted_empty_rows"], 1)
        result = self.report(memberships=self.members(), omit_empty_rows=False)
        self.assertEqual(self.mask(result, "User:alice", resource="secrets"), "........")
        result = self.report(memberships=self.members(complete=False))
        self.assertEqual(self.mask(result, "User:alice", resource="secrets"), "????????")
        self.assertEqual(result["summary"]["omitted_empty_rows"], 0)

    def test_declarations_follow_visible_subjects_inherited_groups_and_namespace_selection(self):
        self.local_user()
        self.cfg = config(True, mode="matrix")
        self.add_namespace("kube-system")
        for kind, name, ns, subject in (
                ("AuthorizationRule", "system-only", "kube-system", {"kind": "User", "name": "alice"}),
                ("ClusterAuthorizationRule", "unrelated", "", {"kind": "Group", "name": "other"}),
                ("ClusterAuthorizationRule", "team", "", {"kind": "Group", "name": "team"})):
            meta = {"name": name}
            if ns:
                meta["namespace"] = ns
            self.api.store({"apiVersion": "deckhouse.io/v1", "kind": kind, "metadata": meta,
                            "spec": {"accessLevel": "User", "subjects": [subject]}})
        result = self.report(subjects={"groups": False}, memberships=self.members(groups=["team"]))
        declarations = records(result, "bindings.csv")
        self.assertEqual([row["binding_name"] for row in declarations], ["team"])
        self.assertEqual(json.loads(declarations[0]["resolved_namespaces"]), ["dev", "test"])
        self.assertEqual({r["subject"] for r in records(result, "subjects.csv")}, {"User:alice"})

    def test_broad_admin_readonly_groups_members_and_direct_users_do_not_seed_rows(self):
        self.local_user("bob")
        self.local_user("carol")
        for name, verbs, kind in (("admins", ["*"], "Group"), ("readers", ["get", "list"], "Group"),
                                  ("direct-admin", ["*"], "User")):
            role = self.api.role(name, [rule(["*"], verbs, group="*")])
            self.api.bind(name, role, [{"kind": kind, "name": name}], namespace="")
        normal = self.api.role("normal", [rule(["pods"], ["get"])])
        self.api.bind("normal", normal, [{"kind": "User", "name": "alice"}])
        members = self.members("bob", ["admins"], complete=False) + self.members("carol", ["readers"])
        result = self.report(memberships=members)
        self.assertEqual({r["subject"] for r in records(result, "subjects.csv")}, {"User:alice"})
        self.assertEqual({(r["namespace"], r["resource"]) for r in records(result)}, {("dev", "pods")})
        self.assertEqual(self.mask(result, "User:alice"), "G.......")
        self.assertEqual({r["binding_name"] for r in records(result, "bindings.csv")}, {"normal"})
        self.assertEqual(result["summary"]["excluded_broad_subjects"], 5)
        self.assertEqual(set(result["summary"]["excluded_broad_subject_names"]),
                         {"Group:admins", "Group:readers", "User:bob", "User:carol", "User:direct-admin"})
        # Disabling the filter restores columns, inherited grants, and wildcard rows.
        full = self.report(exclude_broad_subjects=False, memberships=members)
        self.assertGreater(full["summary"]["rows"], result["summary"]["rows"])
        self.assertEqual(self.mask(full, "User:bob"), "glwcupdx")
        self.assertEqual(full["summary"]["excluded_broad_subjects"], 0)

    def test_broad_filter_keeps_named_resources_specific_api_groups_and_narrow_admin_role(self):
        for name, rules in (("named", [rule(["*"], ["*"], group="*", resourceNames=["*"])]),
                            ("core-only", [rule(["*"], ["get"])]),
                            ("cluster-admin", [rule(["pods"], ["*"]) ])):
            role = self.api.role(name, rules)
            self.api.bind(name, role, [{"kind": "User", "name": name}])
        result = self.report()
        self.assertEqual(result["summary"]["excluded_broad_subjects"], 0)
        self.assertEqual({r["name"] for r in records(result, "subjects.csv") if r["kind"] == "User"},
                         {"named", "core-only", "cluster-admin"})

    def test_broad_filter_is_scoped_to_selected_namespaces(self):
        role = self.api.role("local-wide", [rule(["*"], ["list"], group="*")])
        self.api.bind("local-wide", role, [{"kind": "User", "name": "alice"}], namespace="dev")
        self.assertIn("User:alice", self.report()["summary"]["excluded_broad_subject_names"])
        other = self.report(namespaces=["test"], memberships=self.members())
        self.assertEqual(other["summary"]["excluded_broad_subjects"], 0)
        self.assertEqual({r["subject"] for r in records(other, "subjects.csv")}, {"User:alice"})
        self.assertEqual(self.report(namespace_include=["absent-*"], include_cluster_scoped=False,
                                     memberships=self.members())["summary"]["excluded_broad_subjects"], 0)

    def test_broad_filter_propagates_nested_deckhouse_membership(self):
        self.cfg = config(True, mode="matrix")
        self.api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "alice"},
                        "spec": {"email": "alice@example.org"}})
        for name, claim, members in (("child", "team", [{"kind": "User", "name": "alice"}]),
                                     ("parent", "admins", [{"kind": "Group", "name": "child"}])):
            self.api.store({"apiVersion": "deckhouse.io/v1alpha1", "kind": "Group", "metadata": {"name": name},
                            "spec": {"name": claim, "members": members}})
        role = self.api.role("wide", [rule(["*"], ["watch"], group="*")])
        self.api.bind("wide", role, [{"kind": "Group", "name": "admins"}], namespace="")
        result = self.report()
        self.assertEqual(set(result["summary"]["excluded_broad_subject_names"]),
                         {"Group:admins", "Group:team", "User:alice@example.org"})
        self.assertEqual(records(result), [])
        self.assertEqual(records(result, "bindings.csv"), [])
        self.assertEqual(records(result, "subjects.csv"), [])

    def test_external_users_show_only_direct_grants_on_both_platforms(self):
        for deckhouse in (False, True):
            with self.subTest(deckhouse=deckhouse):
                self.api = MatrixAPI()
                self.cfg = config(deckhouse, mode="matrix")
                direct = self.api.role("direct", [rule(["pods"], ["get"]),
                                                      rule(["roles"], ["bind"], group="rbac.authorization.k8s.io")])
                inherited = self.api.role("group", [rule(["pods"], ["list"]), rule(["secrets"], ["get"])])
                self.api.bind("direct", direct, [{"kind": "User", "name": "ldap-alice"}])
                for group in ("system:authenticated", "ldap:readers"):
                    self.api.bind(group, inherited, [{"kind": "Group", "name": group}])
                report = self.report(memberships=self.members("ldap-alice", ["ldap:readers"], complete=False))
                self.assertEqual(self.mask(report, "User:ldap-alice"), "G.......")
                self.assertEqual(self.mask(report, "User:ldap-alice", resource="secrets"), "........")
                self.assertEqual(self.mask(report, "User:ldap-alice", resource="roles",
                                           group="rbac.authorization.k8s.io", action="bind"), "Y")
                sources = [r for r in records(report, "bindings.csv") if r["subject"] == "User:ldap-alice"]
                self.assertEqual({r["origin"] for r in sources}, {"direct"})
                self.assertEqual({r["binding_name"] for r in sources}, {"direct"})
                subject = next(r for r in records(report, "subjects.csv") if r["subject"] == "User:ldap-alice")
                self.assertEqual(subject["rights_basis"], "direct_only")
                self.assertEqual(subject["membership_complete"], "false")
                self.assertFalse(any("membership is incomplete" in w for w in report["warnings"]))
                # Hidden groups must not retain rows merely because the user is external.
                filtered = self.report(subjects={"groups": False})
                self.assertEqual({r["resource"] for r in records(filtered)}, {"pods", "roles"})
                self.assertNotIn("?", filtered["files"]["matrix.csv"])
                # Broad group membership must not hide an external user's direct grants.
                wide = self.api.role("wide", [rule(["*"], ["*"], group="*")])
                self.api.bind("wide", wide, [{"kind": "Group", "name": "system:authenticated"}], namespace="")
                self.assertIn("User:ldap-alice", self.report()["files"]["matrix.csv"])

    def test_default_report_keeps_external_groups_and_hides_external_user_rules(self):
        read = self.api.role("read", [rule(["pods"], ["get"])])
        secrets = self.api.role("direct-secret", [rule(["secrets"], ["get"])])
        self.api.bind("ldap-group", read, [{"kind": "Group", "name": "ldap:readers"}])
        self.api.bind("ldap-user", secrets, [{"kind": "User", "name": "ldap-alice@example.org"}])
        report = Matrix(self.api, self.cfg, {}).report()
        self.assertEqual({r["subject"] for r in records(report, "subjects.csv")}, {"Group:ldap:readers"})
        self.assertEqual({r["resource"] for r in records(report)}, {"pods"})
        self.assertEqual(self.mask(report, "Group:ldap:readers"), "G.......")
        self.assertEqual(report["summary"]["excluded_external_users"], 1)
        self.assertNotIn("ldap-alice@example.org", report["files"]["bindings.csv"])

    def test_local_deckhouse_user_is_complete_from_live_groups_and_legacy_groups(self):
        self.cfg = config(True, mode="matrix")
        user = {"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": "local"},
                "spec": {"email": "alice@example.org", "groups": ["legacy-readers"]}}
        self.api.store(user)
        read = self.api.role("read", [rule(["pods"], ["get"])])
        self.api.bind("legacy", read, [{"kind": "Group", "name": "legacy-readers"}])
        report = Matrix(self.api, self.cfg, {}).report()
        self.assertEqual(self.mask(report, "User:alice@example.org"), "g.......")
        subject = next(r for r in records(report, "subjects.csv") if r["subject"] == "User:alice@example.org")
        self.assertEqual(subject["membership_complete"], "true")
        self.assertEqual(subject["rights_basis"], "direct_and_groups")
        disabled = Matrix(self.api, self.cfg, {"resolve_group_membership": False}).report()
        self.assertEqual(self.mask(disabled, "User:alice@example.org"), "????????")
        # Removing membership in Kubernetes must remove inherited rights on the next read.
        user["spec"]["groups"] = []
        self.api.store(user)
        report = Matrix(self.api, self.cfg, {}).report()
        self.assertEqual(self.mask(report, "User:alice@example.org"), "........")

    def test_ambiguous_local_emails_or_group_claims_stop_completeness_inference(self):
        self.cfg = config(True, mode="matrix")
        for name, email in (("first", "alice@example.org"), ("second", "ALICE@example.org")):
            self.api.store({"apiVersion": "deckhouse.io/v1", "kind": "User", "metadata": {"name": name},
                            "spec": {"email": email}})
        with self.assertRaisesRegex(AccessError, "Ambiguous local"):
            self.report()

    def test_validation_rejects_unknown_options_and_duplicate_memberships(self):
        for raw in ({"namespace_mode": "invalid"}, {"namespace_include": "dev*"},
                    {"users_exclude": [""]}, {"include_system_subjects": "false"}, {"omit_empty_rows": 1}, {"exclude_broad_subjects": "true"}, {"include_external_users": "true"},
                    {"verification": {"enabled": True}}, {"csv": {"delimiter": "||"}},
                    {"memberships": self.members() * 2}, {"subjects": {"users": "yes"}},
                    {"memberships": [{"kind": "Group", "name": "devs", "groups": [], "complete": True}]}):
            with self.subTest(raw=raw), self.assertRaises(AccessError):
                validate_matrix(raw)


def compact_report(result):
    return json.dumps(result, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
