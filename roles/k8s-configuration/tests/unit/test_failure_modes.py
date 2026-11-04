import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import FakeAPI, config, grant, engine, HASH
from access_manager.client import APIError
from access_manager.schema import AccessError
from access_manager.export import export_state


class FailureModes(unittest.TestCase):
    def test_post_response_lost_is_observed_without_duplicate_write(self):
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        original = api.request
        writes = []

        def lost(method, path, body=None, query=None):
            result = original(method, path, body, query)
            if method == "POST":
                writes.append(path)
                raise AccessError("Response lost")
            return result

        api.request = lost
        self.assertTrue(e.apply())
        self.assertEqual(len(writes), 1)
        api.request = original
        self.assertFalse(engine(api, grants=[grant()]).apply())

    def test_patch_response_lost_is_reconciled(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        new = grant(subjects=[{"kind": "User", "name": "new-user"}])
        e = engine(api, grants=[new])
        original = api.request

        def lost(method, path, body=None, query=None):
            result = original(method, path, body, query)
            if method == "PATCH":
                raise AccessError("Response lost")
            return result

        api.request = lost
        self.assertTrue(e.apply())
        api.request = original
        self.assertFalse(engine(api, grants=[new]).apply())

    def test_patch_race_after_last_get_stops_on_precondition(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        e = engine(
            api, grants=[grant(subjects=[{"kind": "User", "name": "new"}])]
        )
        original = api.request

        def race(method, path, body=None, query=None):
            if method == "PATCH":
                api.objects[path]["metadata"]["resourceVersion"] = "other-writer"
            return original(method, path, body, query)

        api.request = race
        with self.assertRaises(APIError) as caught:
            e.apply()
        self.assertEqual(caught.exception.status, 422)
        self.assertFalse(e.changed)
        self.assertEqual(e.completed, [])

    def test_create_conflict_never_silently_accepted(self):
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        original = api.request

        def race(method, path, body=None, query=None):
            if method == "POST":
                api.store(body)
            return original(method, path, body, query)

        api.request = race
        with self.assertRaises(APIError) as caught:
            e.apply()
        self.assertEqual(caught.exception.status, 409)
        self.assertFalse(e.changed)

    def test_delete_race_does_not_remove_another_version(self):
        api = FakeAPI()
        engine(api, grants=[grant()]).apply()
        e = engine(api, grants=[grant(state="absent")])
        original = api.request

        def race(method, path, body=None, query=None):
            if method == "DELETE":
                api.objects[path]["metadata"]["resourceVersion"] = "other-writer"
            return original(method, path, body, query)

        api.request = race
        with self.assertRaises(APIError) as caught:
            e.apply()
        self.assertEqual(caught.exception.status, 409)
        self.assertTrue(any(o.get("kind") == "RoleBinding" for o in api.objects.values()))

    def test_namespace_labels_changed_after_plan(self):
        api = FakeAPI()
        e = engine(api, grants=[grant()])
        api.objects["/api/v1/namespaces/dev"]["metadata"]["labels"]["env"] = "different"
        with self.assertRaises(AccessError):
            e.apply()
        self.assertFalse(any(c[0] != "GET" for c in api.calls))

    def test_repeated_pagination_token_fails_closed(self):
        api = FakeAPI()
        original = api.request

        def broken(method, path, body=None, query=None):
            if path.endswith("/rolebindings"):
                return {"items": [], "metadata": {"continue": "same"}}
            return original(method, path, body, query)

        api.request = broken
        with self.assertRaises(AccessError):
            engine(api, grants=[grant()])


    def test_service_account_api_default_is_idempotent(self):
        api = FakeAPI()
        api.store(
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {"name": "runner", "namespace": "dev"},
            }
        )
        g = grant(
            subjects=[
                {
                    "kind": "ServiceAccount",
                    "namespace": "dev",
                    "name": "runner",
                }
            ]
        )
        e = engine(api, grants=[g])
        e.apply()
        for obj in api.objects.values():
            if obj.get("kind") == "RoleBinding":
                obj["subjects"][0]["apiGroup"] = ""
        self.assertFalse(engine(api, grants=[g]).apply())

    def test_identity_fields_do_not_affect_assignment_export(self):
        api = FakeAPI()
        user = {
            "name": "jane",
            "source": "static",
            "email": "jane@example.org",
            "password_hash": HASH,
        }
        g = grant(subjects=[{"kind": "User", "name": "jane@example.org"}])
        api.store({"apiVersion": "deckhouse.io/v1", "kind": "User",
                   "metadata": {"name": "jane"},
                   "spec": {"email": user["email"], "password": HASH, "ttl": "1h"}})
        engine(api, config(True), grants=[g]).apply()
        out = export_state(engine(api, config(True)), {"mode": "managed"})
        self.assertTrue(out["inventory"]["k8s_configuration_grants"])
        self.assertEqual(set(out["inventory"]), {"k8s_configuration_grants"})
        self.assertTrue(all(r["source"]["kind"] not in ("User", "Group") for r in out["audit"]))
        self.assertNotIn(HASH, json.dumps(out))

    def test_legacy_rbac_path_segment_name_round_trip(self):
        api = FakeAPI()
        g = grant(target_name="legacy:readers")
        engine(api, grants=[g]).apply()
        out = export_state(engine(api), {"mode": "managed"})
        entries = out["inventory"]["k8s_configuration_grants"]
        self.assertEqual(entries[0]["target_name"], "legacy:readers")
        self.assertEqual(engine(api, grants=entries).report()["summary"]["create"], 0)
        self.assertFalse(engine(api, grants=[g]).apply())

    def test_prune_does_not_require_authorization_checks(self):
        api = FakeAPI()
        engine(api, grants=[grant("old")]).apply()
        api.calls.clear()
        api.access_allowed = False
        e = engine(api, config(management={"prune": True}), grants=[grant("new")])
        self.assertTrue(e.apply())
        self.assertTrue(any(c[0] == "DELETE" for c in api.calls))
        self.assertFalse(any("subjectaccessreviews" in c[1] for c in api.calls))

    def test_deckhouse_without_ready_condition_applies_without_sar(self):
        api = FakeAPI()
        cfg = config(True)
        cfg["deckhouse"]["profiles"]["fixture"]["authz_ready_condition"] = None
        grant_spec = {
            "id": "basic", "backend": "deckhouse", "accessLevel": "User",
            "subjects": [{"kind": "Group", "name": "readers"}],
            "scope": {"namespaces": ["dev"]},
        }
        self.assertTrue(engine(api, cfg, grants=[grant_spec]).apply())
        self.assertFalse(engine(api, cfg, grants=[grant_spec]).apply())
        self.assertFalse(any("subjectaccessreviews" in c[1] for c in api.calls))

    def test_existing_car_requires_mixed_profile_for_same_rbac_subject(self):
        api = FakeAPI()
        basic = {
            "id": "basic",
            "backend": "deckhouse",
            "subjects": [{"kind": "Group", "name": "readers"}],
            "accessLevel": "User",
            "scope": {"namespaces": ["dev"]},
        }
        engine(api, config(True), grants=[basic]).apply()
        cfg = config(True)
        cfg["deckhouse"]["profiles"]["fixture"]["mixed_backends"] = False
        with self.assertRaises(AccessError):
            engine(api, cfg, grants=[grant()])


if __name__ == "__main__":
    unittest.main()
