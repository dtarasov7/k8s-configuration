"""Additional discovery resources for audit tests, with no workload/secret reads."""
from support import FakeAPI
from access_manager.render import RBAC


class MatrixAPI(FakeAPI):
    omit_type_meta = False

    def request(self, method, path, body=None, query=None):
        if method == "GET" and path == "/apis/apps/v1":
            self.calls.append((method, path, body, query))
            return {"resources": [
                {"name": "deployments", "kind": "Deployment", "namespaced": True},
                {"name": "deployments/scale", "kind": "Scale", "namespaced": True},
            ]}
        result = super().request(method, path, body, query)
        if self.omit_type_meta and method == "GET" and "items" in result:
            for obj in result["items"]:
                obj.pop("kind", None)
                obj.pop("apiVersion", None)
        if method == "GET" and path == "/apis":
            version = {"groupVersion": "apps/v1", "version": "v1"}
            result["groups"].append({"name": "apps", "preferredVersion": version, "versions": [version]})
        if method == "GET" and path == "/api/v1":
            for name in ("pods", "pods/log", "pods/exec", "configmaps", "secrets", "nodes"):
                result["resources"].append({"name": name, "kind": name.title(), "namespaced": name != "nodes"})
        return result

    def role(self, name, rules, namespace=None, **fields):
        meta = {"name": name}
        if namespace:
            meta["namespace"] = namespace
        return self.store(dict(apiVersion=RBAC, kind="Role" if namespace else "ClusterRole",
                               metadata=meta, rules=rules, **fields))

    def bind(self, name, role, subjects, namespace="dev", **metadata):
        meta = dict(name=name, **metadata)
        if namespace:
            meta["namespace"] = namespace
        return self.store({
            "apiVersion": RBAC, "kind": "RoleBinding" if namespace else "ClusterRoleBinding",
            "metadata": meta,
            "roleRef": {"apiGroup": RBAC.split("/")[0], "kind": role["kind"], "name": role["metadata"]["name"]},
            "subjects": subjects,
        })


def rule(resources, verbs, group="", **extra):
    return dict(apiGroups=[group], resources=resources, verbs=verbs, **extra)
