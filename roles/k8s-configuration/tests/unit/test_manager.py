import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import FakeAPI, config, grant, engine
from access_manager.schema import AccessError, validate_config, validate_inventory
from access_manager.render import identity, keys, clean
from access_manager.reconcile import patch_for
from access_manager.export import export_state


class ManagerTests(unittest.TestCase):
    def assertBlocked(self, call):
        with self.assertRaises(AccessError):
            call()

    def test_plan_is_read_only_and_deterministic(self):
        api = FakeAPI()
        first = engine(api, grants=[grant()])
        second = engine(api, grants=[grant()])
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.report()["summary"]["create"], 1)
        self.assertTrue(all(c[0] == "GET" for c in api.calls))

    def test_dry_default_and_legacy_plan_alias(self):
        self.assertEqual(config()["mode"], "dry")
        self.assertEqual(config(mode="plan")["mode"], "dry")
        self.assertBlocked(lambda: config(mode="unknown"))

    def test_plan_summary_separates_add_change_and_remove(self):
        api = FakeAPI()
        engine(api, grants=[grant("old"), grant("changed"), grant("unchanged")]).apply()
        changed = grant("changed", subjects=[{"kind": "User", "name": "manual"}])
        e = engine(api, config(management={"prune": True}), grants=[changed, grant("new"), grant("unchanged")])
        report = e.report()
        self.assertEqual(report["summary"]["noop"], 1)
        self.assertEqual({c["action"] for c in report["changes"]}, {"create", "update", "delete"})
        self.assertEqual(len(report["changes"]), 3)
        planned = report["planned"]
        self.assertEqual([len(planned[k]) for k in ("add", "change", "remove")], [1, 1, 1])
        self.assertEqual(planned["change"][0]["action"], "update")

    def test_apply_then_noop_and_foreign_metadata_preserved(self):
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        self.assertTrue(e.apply())
        key = next(iter(e.desired))
        obj = api.objects[api.path(*key)]
        obj["metadata"]["annotations"]["foreign"] = "keep"
        obj["metadata"]["labels"]["foreign"] = "keep"
        e2 = engine(api, grants=[grant()])
        self.assertFalse(e2.apply())
        report = e2.report()
        self.assertEqual(report["changes"], [])
        self.assertEqual(report["planned"], {"add": [], "change": [], "remove": []})
        self.assertEqual(report["summary"], {"create": 0, "update": 0, "replace": 0, "delete": 0, "noop": 1})
        self.assertEqual(api.objects[api.path(*key)]["metadata"]["annotations"]["foreign"], "keep")

    def test_subject_update(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        g = grant(subjects=[{"kind": "User", "name": "jane"}])
        e = engine(api, grants=[g])
        self.assertEqual(e.report()["summary"]["update"], 1)
        e.apply()
        self.assertFalse(engine(api, grants=[g]).apply())

    def test_role_binding_to_local_role(self):
        e = engine(grants=[grant(roleRef={"kind": "Role", "name": "local"})])
        self.assertEqual(e.report()["summary"]["create"], 1)
        self.assertBlocked(
            lambda: engine(
                grants=[grant(roleRef={"kind": "Role", "name": "local"}, scope={"cluster": True})]
            )
        )

    def test_unknown_input_and_empty_selector(self):
        self.assertBlocked(
            lambda: validate_config({"connection": {"kubeconfig": "/x"}, "mdoe": "apply"})
        )
        self.assertBlocked(lambda: engine(grants=[grant(typo=True)]))
        self.assertBlocked(lambda: engine(grants=[grant(scope={"namespaces": []})]))
        self.assertBlocked(
            lambda: engine(
                cfg=config(True),
                grants=[
                    grant(
                        backend="deckhouse",
                        roleRef=None,
                        accessLevel="User",
                        scope={"namespace_selector": {}},
                    )
                ],
            )
        )
        self.assertBlocked(
            lambda: engine(
                grants=[grant(scope={"cluster": True, "include_system_namespaces": False})]
            )
        )

    def test_cluster_binding_to_role_rejected(self):
        self.assertBlocked(
            lambda: engine(
                grants=[grant(roleRef={"kind": "Role", "name": "local"}, scope={"cluster": True})]
            )
        )


    def test_role_ref_replace_requires_opt_in_and_counts_deletion(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        changed = grant(roleRef={"kind": "ClusterRole", "name": "edit"})
        self.assertBlocked(lambda: engine(api, grants=[changed]))
        self.assertBlocked(
            lambda: engine(
                api,
                config(safety={"allow_binding_replacement": True, "max_deletions": 0}),
                grants=[changed],
            )
        )
        e = engine(api, config(safety={"allow_binding_replacement": True}), grants=[changed])
        self.assertEqual(e.report()["summary"]["replace"], 1)
        self.assertTrue(e.apply())
        self.assertFalse(engine(api, grants=[changed]).apply())

    def test_unmanaged_and_wrong_uid_adoption(self):
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        obj = copy.deepcopy(next(iter(e.desired.values())))
        obj["metadata"]["labels"] = {}
        obj["metadata"]["annotations"] = {}
        saved = api.store(obj)
        self.assertBlocked(lambda: engine(api, grants=[grant()]))
        ref = {
            "group": "rbac.authorization.k8s.io",
            "resource": "rolebindings",
            "namespace": "dev",
            "name": saved["metadata"]["name"],
            "uid": "wrong",
        }
        self.assertBlocked(
            lambda: engine(api, config(management={"adoption": [ref]}), grants=[grant()])
        )
        ref["uid"] = saved["metadata"]["uid"]
        adopt = engine(api, config(management={"adoption": [ref]}), grants=[grant()])
        self.assertTrue(adopt.apply())
        self.assertFalse(engine(api, grants=[grant()]).apply())

    def test_controller_resources_never_adopted(self):
        for marker in ("owner", "helm", "deckhouse"):
            api = FakeAPI()
            e = engine(api, grants=[grant()])
            obj = next(iter(e.desired.values()))
            if marker == "owner":
                obj["metadata"]["ownerReferences"] = [{"uid": "controller"}]
            elif marker == "helm":
                obj["metadata"]["annotations"]["meta.helm.sh/release-name"] = "release"
            else:
                obj["metadata"]["labels"]["rbac.deckhouse.io/automated"] = "true"
            api.store(obj)
            self.assertBlocked(lambda: engine(api, grants=[grant()]))

    def test_prune_omitted_empty_and_foreign(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        cfg = config(management={"prune": True})
        self.assertEqual(engine(api, cfg).report()["summary"]["delete"], 0)
        self.assertBlocked(lambda: engine(api, cfg, grants=[]))
        cfg["safety"]["allow_empty_desired"] = True
        foreign = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": "foreign"},
            "roleRef": {"kind": "ClusterRole", "name": "view"},
            "subjects": [],
        }
        api.store(foreign)
        e = engine(api, cfg, grants=[])
        self.assertEqual(e.report()["summary"]["delete"], 1)
        e.apply()
        self.assertIn("/apis/rbac.authorization.k8s.io/v1/clusterrolebindings/foreign", api.objects)

    def test_prune_namespace_scope(self):
        api = FakeAPI()
        engine(api, grants=[grant(scope={"namespaces": ["dev", "test"]})]).apply()
        cfg = config(
            management={"prune": True, "namespaces": ["dev"], "include_cluster_scoped": False},
            safety={"allow_empty_desired": True},
        )
        e = engine(api, cfg, grants=[])
        self.assertEqual(e.report()["summary"]["delete"], 1)
        e.apply()
        self.assertTrue(
            any(
                o.get("kind") == "RoleBinding" and o["metadata"].get("namespace") == "test"
                for o in api.objects.values()
            )
        )

    def test_explicit_absent_uses_same_safety(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        e = engine(api, grants=[grant(state="absent")])
        self.assertEqual(e.report()["summary"]["delete"], 1)
        self.assertTrue(e.apply())
        self.assertEqual(
            engine(api, grants=[grant(state="absent")]).report()["summary"]["delete"], 0
        )

    def test_protected_namespace_and_objects(self):
        self.assertBlocked(lambda: engine(grants=[grant(scope={"namespaces": ["kube-system"]})]))
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        name = next(iter(e.desired.values()))["metadata"]["name"]
        self.assertBlocked(
            lambda: engine(
                api,
                config(
                    safety={
                        "protected_objects": [
                            {
                                "group": "rbac.authorization.k8s.io",
                                "resource": "rolebindings",
                                "namespace": "dev",
                                "name": name,
                            }
                        ]
                    }
                ),
                grants=[grant()],
            )
        )

    def test_concurrent_update_stops_before_writes(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        e = engine(
            api, grants=[grant(subjects=[{"kind": "User", "name": "new"}])]
        )
        key = next(iter(e.desired))
        api.objects[api.path(*key)]["metadata"]["resourceVersion"] = "concurrent"
        api.calls = []
        self.assertBlocked(e.apply)
        self.assertTrue(all(c[0] == "GET" for c in api.calls))

    def test_permission_read_failure_not_empty(self):
        api = FakeAPI()

        def deny(method, path, body):
            if path.endswith("/rolebindings"):
                raise AccessError("403")

        api.fail = deny
        self.assertBlocked(lambda: engine(api, grants=[grant()]))
        self.assertTrue(all(c[0] == "GET" for c in api.calls))

    def test_pagination_complete(self):
        api = FakeAPI()
        api.page_size = 1
        e = engine(api, grants=[grant(scope={"namespaces": ["dev", "test"]})])
        self.assertEqual(len(e.namespaces), 5)
        e.apply()
        self.assertEqual(
            engine(api, grants=[grant(scope={"namespaces": ["dev", "test"]})]).report()["summary"][
                "noop"
            ],
            2,
        )

    def test_partial_apply_does_not_prune(self):
        api = FakeAPI()
        engine(api, grants=[grant("old")]).apply()
        e = engine(api, config(management={"prune": True}), grants=[grant("a"), grant("b")])
        count = [0]

        def fail_second(method, path, body):
            if method == "POST":
                count[0] += 1
                if count[0] == 2:
                    raise AccessError("write failed")

        api.fail = fail_second
        self.assertBlocked(e.apply)
        self.assertTrue(e.changed)
        self.assertEqual(len(e.completed), 1)
        self.assertFalse(any(c[0] == "DELETE" for c in api.calls))

    def test_plan_digest_changes_on_observed_role_change(self):
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        cfg = config(expected_plan_digest=e.digest)
        engine(api, cfg, grants=[grant()])
        api.objects["/apis/rbac.authorization.k8s.io/v1/clusterroles/view"]["metadata"][
            "resourceVersion"
        ] = "2"
        self.assertBlocked(lambda: engine(api, cfg, grants=[grant()]))


    def test_deckhouse_disabled_module_even_with_crd(self):
        api = FakeAPI()
        api.objects["/apis/deckhouse.io/v1alpha1/moduleconfigs/user-authz"]["spec"][
            "enabled"
        ] = False
        self.assertBlocked(lambda: engine(api, config(True), grants=[grant()]))

    def test_deckhouse_capability_discovery_ignores_deployment(self):
        self.assertEqual(engine(cfg=config(platform="deckhouse")).profile["api_versions"], {})
        api = FakeAPI()
        api.objects["/apis/apps/v1/namespaces/d8-system/deployments/deckhouse"]["spec"]["template"][
            "spec"
        ]["containers"][0]["image"] = "different"
        engine(api, config(True))
        self.assertFalse(any("deployments/deckhouse" in str(call) for call in api.calls))

    def test_ready_module_without_moduleconfig_or_deployment(self):
        api = FakeAPI()
        del api.objects["/apis/deckhouse.io/v1alpha1/moduleconfigs/user-authz"]
        del api.objects["/apis/apps/v1/namespaces/d8-system/deployments/deckhouse"]
        e = engine(api, config(platform="deckhouse"), grants=[grant()])
        self.assertEqual(e.authz_config, {})
        self.assertTrue(e.apply())

    def test_module_state_and_crd_capabilities_are_required(self):
        for field, value in (("phase", "Error"), ("EnabledByModuleManager", "False"), ("IsReady", "False")):
            api = FakeAPI()
            status = api.objects["/apis/deckhouse.io/v1alpha1/modules/user-authz"]["status"]
            if field == "phase":
                status[field] = value
            else:
                next(c for c in status["conditions"] if c["type"] == field)["status"] = value
            self.assertBlocked(lambda: engine(api, config(platform="deckhouse"), grants=[grant()]))
        for mutation in ("established", "served", "schema"):
            api = FakeAPI()
            crd = api.objects["/apis/apiextensions.k8s.io/v1/customresourcedefinitions/authorizationrules.deckhouse.io"]
            if mutation == "established":
                crd["status"]["conditions"][0]["status"] = "False"
            elif mutation == "served":
                crd["spec"]["versions"][0]["served"] = False
            else:
                del crd["spec"]["versions"][0]["schema"]
            self.assertBlocked(lambda: engine(api, config(platform="deckhouse"), grants=[grant()]))

    def test_missing_moduleconfig_is_guarded_against_appearance_before_apply(self):
        api = FakeAPI()
        path = "/apis/deckhouse.io/v1alpha1/moduleconfigs/user-authz"
        old = api.objects.pop(path)
        e = engine(api, config(platform="deckhouse"), grants=[grant()])
        api.objects[path] = old
        self.assertBlocked(e.apply)
        self.assertFalse(any(call[0] != "GET" for call in api.calls))

    def deck_grant(self, **kw):
        g = {
            "id": "basic",
            "backend": "deckhouse",
            "subjects": [{"kind": "Group", "name": "devs"}],
            "accessLevel": "User",
            "scope": {"namespace_selector": {"matchLabels": {"env": "review"}}},
        }
        g.update(kw)
        return g

    def test_deckhouse_car_selector_and_multitenancy(self):
        api = FakeAPI()
        e = engine(api, config(True), grants=[self.deck_grant()])
        self.assertTrue(e.apply())
        self.assertFalse(engine(api, config(True), grants=[self.deck_grant()]).apply())
        api.objects["/apis/deckhouse.io/v1alpha1/moduleconfigs/user-authz"]["spec"]["settings"][
            "enableMultiTenancy"
        ] = False
        self.assertBlocked(lambda: engine(api, config(True), grants=[self.deck_grant()]))

    def test_deckhouse_selector_matching_system_rejected(self):
        self.assertBlocked(
            lambda: engine(
                cfg=config(True),
                grants=[
                    self.deck_grant(
                        scope={"namespace_selector": {"matchLabels": {"env": "system"}}}
                    )
                ],
            )
        )

    def test_deckhouse_options_and_selector_removal(self):
        api = FakeAPI()
        engine(api, config(True), grants=[self.deck_grant()]).apply()
        g = self.deck_grant(scope={"cluster": True, "include_system_namespaces": False})
        e = engine(api, config(True), grants=[g])
        self.assertEqual(e.report()["summary"]["update"], 1)
        e.apply()
        obj = next(o for o in api.objects.values() if o.get("kind") == "ClusterAuthorizationRule")
        self.assertNotIn("namespaceSelector", obj["spec"])


    def test_subject_names_are_literal_and_export_has_no_source(self):
        api = FakeAPI()
        subjects = [{"kind": "User", "name": "Jane@EXAMPLE.org"},
                    {"kind": "Group", "name": "ldap:readers"}]
        engine(api, grants=[grant(subjects=subjects)]).apply()
        exported = export_state(engine(api), {"mode": "managed"})
        grants = exported["inventory"]["k8s_configuration_grants"]
        self.assertCountEqual(grants[0]["subjects"], subjects)
        engine(api, grants=grants).apply()
        self.assertFalse(engine(api, grants=grants).apply())

    def test_export_round_trip_preserves_binding_name(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        e = engine(api)
        out = export_state(e, {"mode": "managed", "namespaces": ["dev"]})
        entries = out["inventory"]["k8s_configuration_grants"]
        self.assertEqual(len(entries), 1)
        roundtrip = engine(api, grants=entries)
        self.assertEqual(roundtrip.report()["summary"]["create"], 0)
        roundtrip.apply()  # Export IDs may update the provenance annotation only.
        self.assertFalse(engine(api, grants=entries).apply())

    def test_default_export_keeps_owned_cluster_grants(self):
        api = FakeAPI()
        engine(api, grants=[grant(scope={"cluster": True})]).apply()
        out = export_state(engine(api), {})
        entries = out["inventory"]["k8s_configuration_grants"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["scope"], {"cluster": True})

    def test_export_filter_and_dynamic_selector(self):
        api = FakeAPI()
        engine(api, config(True), grants=[self.deck_grant()]).apply()
        e = engine(api, config(True))
        empty = export_state(
            e, {"mode": "scoped", "access_levels": ["User"], "backends": ["deckhouse"],
                "include_cluster_scoped": False}
        )
        self.assertFalse(empty["inventory"]["k8s_configuration_grants"])
        out = export_state(
            e,
            {
                "mode": "scoped",
                "access_levels": ["User"],
                "backends": ["deckhouse"],
                "include_cluster_scoped": True,
                "namespaces": ["dev"],
            },
        )
        self.assertEqual(
            out["inventory"]["k8s_configuration_grants"][0]["scope"]["namespace_selector"],
            {"matchLabels": {"env": "review"}},
        )
        self.assertTrue(out["audit"][0]["dynamic_scope"])

    def test_export_unsupported_fields_not_silently_lost(self):
        api = FakeAPI()
        engine(api, config(True), grants=[self.deck_grant()]).apply()
        obj = next(o for o in api.objects.values() if o.get("kind") == "ClusterAuthorizationRule")
        obj["spec"]["additionalRoles"] = [{"name": "cluster-admin"}]
        e = engine(api, config(True))
        self.assertBlocked(lambda: export_state(e, {"include_cluster_scoped": True}))
        out = export_state(e, {"include_cluster_scoped": True, "allow_partial": True})
        self.assertFalse(out["inventory"]["k8s_configuration_grants"])
        self.assertFalse(out["audit"][0]["importable"])
        self.assertIn("additionalRoles", out["audit"][0]["unsupported_fields"])

    def test_server_dry_run_does_not_store_objects(self):
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        e.server_validate()
        self.assertFalse(any(o.get("kind") == "RoleBinding" for o in api.objects.values()))
        self.assertTrue(any(c[0] == "POST" and c[3] == {"dryRun": "All"} for c in api.calls))


if __name__ == "__main__":
    unittest.main()
