#!/usr/bin/env python3
"""Live fixture setup/verification, restricted to the disposable kind test context."""
import argparse
import os
import sys
import time
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "module_utils"))
from access_manager.client import Client
from access_manager.schema import validate_config, validate_inventory, require
from access_manager.reconcile import Engine
from access_manager.export import export_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "verify", "cleanup"])
    parser.add_argument("kubeconfig")
    args = parser.parse_args()
    with open(args.kubeconfig) as stream:
        kube = yaml.safe_load(stream)
    require(
        kube.get("current-context") == "kind-kam-role-validation",
        "Live test only accepts kind-kam-role-validation context",
    )
    cfg = validate_config(
        {
            "connection": {"kubeconfig": args.kubeconfig},
            "mode": "apply",
            "management": {
                "owner": "kam-molecule",
                "namespaces": ["kam-role-test"],
                "include_cluster_scoped": False,
            },
            "access_checks": [
                {
                    "user": "kam-test-user",
                    "resourceAttributes": {
                        "namespace": "kam-role-test",
                        "verb": "list",
                        "resource": "pods",
                    },
                    "allowed": True,
                },
                {
                    "user": "kam-test-user",
                    "resourceAttributes": {
                        "namespace": "default",
                        "verb": "list",
                        "resource": "pods",
                    },
                    "allowed": False,
                },
                {
                    "user": "kam-test-user",
                    "resourceAttributes": {
                        "namespace": "kam-role-test",
                        "verb": "get",
                        "resource": "secrets",
                    },
                    "allowed": False,
                },
            ],
        }
    )
    c = Client(cfg["connection"])
    try:
        path = "/api/v1/namespaces/kam-role-test"
        if args.action == "setup":
            if c.get(path, missing=True) is None:
                c.request(
                    "POST",
                    "/api/v1/namespaces",
                    {
                        "apiVersion": "v1",
                        "kind": "Namespace",
                        "metadata": {"name": "kam-role-test", "labels": {"kam-test": "true"}},
                    },
                )
            require(
                c.get(path)["metadata"].get("labels", {}).get("kam-test") == "true",
                "Refusing to reuse foreign namespace",
            )
            print("Fixture namespace ready")
            return
        grant = {
            "id": "reader",
            "backend": "rbac",
            "subjects": [{"kind": "User", "source": "external", "name": "kam-test-user"}],
            "roleRef": {"kind": "ClusterRole", "name": "view"},
            "scope": {"namespaces": ["kam-role-test"]},
        }
        e = Engine(c, cfg, validate_inventory(cfg, grants=[grant]))
        e.prepare()
        if args.action == "verify":
            require(e.report()["summary"]["noop"] == 1, "Molecule binding missing or drifted")
            require(not e.apply(), "Live apply must be idempotent")
            out = export_state(e, {"mode": "managed", "namespaces": ["kam-role-test"]})
            require(len(out["inventory"]["k8s_configuration_grants"]) == 1, "Export failed")
            # Replace roleRef safely, then restore it and verify least privilege.
            changed = dict(grant, roleRef={"kind": "ClusterRole", "name": "edit"})
            cfg["safety"]["allow_binding_replacement"] = True
            cfg["access_checks"] = []
            replacement = Engine(c, cfg, validate_inventory(cfg, grants=[changed]))
            replacement.prepare()
            require(replacement.report()["summary"]["replace"] == 1, "Expected roleRef replacement")
            replacement.apply()
            restore = Engine(c, cfg, validate_inventory(cfg, grants=[grant]))
            restore.prepare()
            restore.apply()
            # Explicit absent and restored access exercise UID-guarded DELETE too.
            absent = dict(grant, state="absent")
            delete = Engine(c, cfg, validate_inventory(cfg, grants=[absent]))
            delete.prepare()
            delete.apply()
            denied = c.request(
                "POST",
                "/apis/authorization.k8s.io/v1/subjectaccessreviews",
                {
                    "apiVersion": "authorization.k8s.io/v1",
                    "kind": "SubjectAccessReview",
                    "spec": {
                        "user": "kam-test-user",
                        "resourceAttributes": {
                            "namespace": "kam-role-test",
                            "verb": "list",
                            "resource": "pods",
                        },
                    },
                },
            )
            require(denied.get("status", {}).get("allowed") is False, "Access not revoked")
            recreate = Engine(c, cfg, validate_inventory(cfg, grants=[grant]))
            recreate.prepare()
            recreate.apply()
            legacy = dict(grant, id="legacy-reader", target_name="kam:legacy-reader")
            legacy_engine = Engine(c, cfg, validate_inventory(cfg, grants=[legacy]))
            legacy_engine.prepare()
            legacy_engine.apply()
            legacy_delete = Engine(
                c, cfg, validate_inventory(cfg, grants=[dict(legacy, state="absent")])
            )
            legacy_delete.prepare()
            legacy_delete.apply()
            print(
                "PASS: live RBAC, idempotence, export, replacement, revocation and negative access checks"
            )
        else:
            namespace = c.get(path, missing=True)
            if namespace:
                require(
                    namespace["metadata"].get("labels", {}).get("kam-test") == "true",
                    "Refusing to delete foreign namespace",
                )
                c.request(
                    "DELETE",
                    path,
                    {
                        "apiVersion": "v1",
                        "kind": "DeleteOptions",
                        "preconditions": {
                            "uid": namespace["metadata"]["uid"],
                            "resourceVersion": namespace["metadata"]["resourceVersion"],
                        },
                    },
                )
            print("Fixture namespace cleanup requested")
    finally:
        c.close()


if __name__ == "__main__":
    main()
