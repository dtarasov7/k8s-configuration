import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "filter_plugins"))
from support import FakeAPI, config, engine, grant
from k8s_configuration_yaml import dry_report


class DryReportTests(unittest.TestCase):
    def test_noop_is_an_empty_plan_with_digest(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        manager = engine(api, grants=[grant()])
        report = dry_report(manager.report())
        self.assertEqual({key: report[key] for key in ("add", "change", "remove")},
                         {"add": [], "change": [], "remove": []})
        self.assertEqual(report["metadata"]["digest"], manager.digest)
        self.assertNotIn("summary", report)
        self.assertNotIn("planned", report)

    def test_mixed_plan_has_no_repeated_objects_and_only_changed_fields(self):
        api = FakeAPI()
        engine(api, grants=[grant("old"), grant("updated"), grant("same")]).apply()
        updated = grant("updated", subjects=[{"kind": "User", "name": "alice"}])
        manager = engine(api, config(management={"prune": True}),
                         grants=[updated, grant("same"), grant("new", scope={"cluster": True})])
        report = dry_report(manager.report())
        self.assertEqual([len(report[key]) for key in ("add", "change", "remove")], [1, 1, 1])
        added = report["add"][0]
        self.assertEqual(added["kind"], "ClusterRoleBinding")
        self.assertNotIn("namespace", added)
        self.assertEqual(added["roleRef"], {"kind": "ClusterRole", "name": "view"})
        self.assertEqual(added["subjects"], [{"kind": "Group", "name": "readers"}])
        fields = report["change"][0]["fields"]
        self.assertEqual(set(fields), {"subjects"})
        self.assertEqual(fields["subjects"]["before"], added["subjects"])
        self.assertEqual(fields["subjects"]["after"], [{"kind": "User", "name": "alice"}])
        text = json.dumps(report)
        for redundant in ("apiVersion", "apiGroup", "resourceVersion", "privilege_change", "adoption", "allow_collision"):
            self.assertNotIn(redundant, text)
        self.assertNotIn("before", report["remove"][0])

    def test_replacement_is_explicit_without_unchanged_subjects(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        manager = engine(api, config(safety={"allow_binding_replacement": True}),
                         grants=[grant(roleRef={"kind": "ClusterRole", "name": "edit"})])
        changed = dry_report(manager.report())["change"][0]
        self.assertTrue(changed["replacement"])
        self.assertEqual(changed["fields"], {"roleRef": {"name": {"before": "view", "after": "edit"}}})

    def test_subject_order_and_crd_false_defaults_are_not_changes(self):
        subjects = [{"kind": "Group", "name": "b"}, {"kind": "Group", "name": "a"}]
        plan = {"changes": [{"action": "update", "kind": "AuthorizationRule", "name": "test",
                            "before": {"spec": {"subjects": subjects, "accessLevel": "User"}},
                            "after": {"spec": {"subjects": list(reversed(subjects)), "accessLevel": "Editor",
                                               "portForwarding": False, "allowScale": False}}}]}
        fields = dry_report(plan)["change"][0]["fields"]
        self.assertEqual(fields, {"spec": {"accessLevel": {"before": "User", "after": "Editor"}}})

    def test_adoption_is_shown_only_when_requested(self):
        api = FakeAPI()
        initial = engine(api, grants=[grant()])
        obj = copy.deepcopy(next(iter(initial.desired.values())))
        obj["metadata"]["labels"] = {}
        obj["metadata"]["annotations"] = {}
        obj = api.store(obj)
        ref = {"group": "rbac.authorization.k8s.io", "resource": "rolebindings", "namespace": "dev",
               "name": obj["metadata"]["name"], "uid": obj["metadata"]["uid"]}
        manager = engine(api, config(management={"adoption": [ref]}), grants=[grant()])
        changed = dry_report(manager.report())["change"][0]
        self.assertTrue(changed["adoption"])
        self.assertNotIn("fields", changed)


    def test_mixed_warning_names_subject_and_both_bindings(self):
        api = FakeAPI()
        native = {"id": "native", "backend": "deckhouse", "accessLevel": "User",
                  "subjects": [{"kind": "Group", "name": "readers"}], "scope": {"namespaces": ["dev"]}}
        first = engine(api, config(True), grants=[native])
        first.apply()
        manager = engine(api, config(True), grants=[grant()])
        warning = next(w for w in manager.report()["warnings"] if w.startswith("Mixed authorization"))
        self.assertIn("Group/readers", warning)
        for obj in list(first.desired.values()) + list(manager.desired.values()):
            self.assertIn(obj["kind"] + "/dev/" + obj["metadata"]["name"], warning)
