"""EN: Render manifests and build deterministic, redacted projections.
RU: Формировать манифесты и детерминированные представления без секретов.
"""
import copy
import hashlib
import json

from .schema import require

RBAC = "rbac.authorization.k8s.io/v1"
KINDS = (
    "RoleBinding",
    "ClusterRoleBinding",
    "AuthorizationRule",
    "ClusterAuthorizationRule",
)
IDENTITIES = ("User", "Group")
AUTHZ = ("AuthorizationRule", "ClusterAuthorizationRule")
SECTION = {k: "grants" for k in KINDS}
OPTIONAL = ("namespaceSelector", "allowAccessToSystemNamespaces", "limitNamespaces")


def canonical(value):
    """EN: Serialize JSON consistently for ordering and digests.
    RU: Сериализовать JSON единообразно для сортировки и отпечатков.

    Args:
        value (Any): JSON-compatible value / JSON-совместимое значение.

    Returns:
        str: Stable JSON representation / Стабильное JSON-представление.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sorted_items(items):
    return sorted(items, key=canonical)


def identity(obj):
    """EN: Extract the kind/namespace/name object key.
    RU: Получить ключ объекта kind/namespace/name.

    Args:
        obj (dict): Kubernetes object with metadata / Объект Kubernetes с metadata.

    Returns:
        tuple[str, str, str]: Namespace is empty for cluster scope / Для кластерной области namespace пуст.
    """
    meta = obj["metadata"]
    return (obj["kind"], meta.get("namespace", ""), meta["name"])


def keys(cfg):
    domain = cfg["management"]["label_domain"]
    return {
        k: domain + "/" + k
        for k in ("owner", "managed-by", "grant-id", "section", "schema-version")
    }


def owned(obj, cfg):
    """EN: Check both ownership labels for the configured owner.
    RU: Проверить обе метки принадлежности настроенному владельцу.

    Args:
        obj (dict): Observed object / Наблюдаемый объект.
        cfg (dict): Role settings / Настройки роли.

    Returns:
        bool: Whether this role owns the object / Принадлежит ли объект этой роли.
    """
    labels = obj.get("metadata", {}).get("labels", {})
    k = keys(cfg)
    return (
        labels.get(k["owner"]) == cfg["management"]["owner"]
        and labels.get(k["managed-by"]) == "ansible"
    )


def controller_owned(obj):
    """EN: Detect standard controller, Helm and Deckhouse ownership markers.
    RU: Обнаружить стандартные признаки управления контроллером, Helm или Deckhouse.

    Args:
        obj (dict): Observed object / Наблюдаемый объект.

    Returns:
        bool: Whether a known marker is present / Есть ли известный признак управления.
    """
    meta = obj.get("metadata", {})
    if meta.get("ownerReferences"):
        return True
    labels = meta.get("labels", {})
    annotations = meta.get("annotations", {})
    if labels.get("rbac.deckhouse.io/automated") == "true":
        return True
    if labels.get("app.kubernetes.io/managed-by", "").lower() in ("helm", "deckhouse"):
        return True
    if any(k.startswith(("meta.helm.sh/", "heritage")) for k in annotations):
        return True
    return any(k.startswith(("user-authz.deckhouse.io/", "heritage")) for k in labels)


def resource_ref(obj):
    """EN: Build an API resource reference including the observed UID.
    RU: Сформировать ссылку на API-ресурс с наблюдаемым UID.

    Args:
        obj (dict): Kubernetes object / Объект Kubernetes.

    Returns:
        dict: Group, kind, namespace, name and UID / Группа API, kind, namespace, имя и UID.
    """
    version = obj["apiVersion"]
    kind, ns, name = identity(obj)
    return {
        "group": version.split("/")[0] if "/" in version else "",
        "kind": kind,
        "namespace": ns,
        "name": name,
        "uid": obj.get("metadata", {}).get("uid"),
    }


def generated_name(cfg, grant, kind, ns):
    """EN: Derive a stable binding name from owner, grant and scope.
    RU: Получить стабильное имя binding из владельца, назначения и области.

    Args:
        cfg (dict): Owner settings / Настройки владельца.
        grant (dict): Assignment with id / Назначение с id.
        kind (str): Resulting resource kind / Kind создаваемого ресурса.
        ns (str): Namespace or empty cluster scope / Namespace или пустая кластерная область.

    Returns:
        str: Deterministic API object name / Детерминированное имя объекта API.
    """
    raw = "\0".join([cfg["management"]["owner"], grant["id"], kind, ns])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return "am-" + grant["id"][:46].rstrip("-.") + "-" + digest


def make(cfg, version, kind, name, ns, section, grant_id=None):
    """EN: Create a manifest skeleton with ownership and provenance metadata.
    RU: Создать основу манифеста с метками владельца и происхождения.

    Args:
        cfg (dict): Ownership settings / Настройки принадлежности.
        version (str): API version / Версия API.
        kind (str): Resource kind / Kind ресурса.
        name (str): Object name / Имя объекта.
        ns (str): Namespace or empty / Namespace или пустая строка.
        section (str): Inventory section / Раздел inventory.
        grant_id (str | None): Optional assignment id / Необязательный id назначения.

    Returns:
        dict: Manifest skeleton / Основа манифеста.
    """
    k = keys(cfg)
    meta = {
        "name": name,
        "labels": {
            k["owner"]: cfg["management"]["owner"],
            k["managed-by"]: "ansible",
            k["section"]: section,
        },
        "annotations": {k["schema-version"]: "1"},
    }
    if grant_id:
        meta["annotations"][k["grant-id"]] = grant_id
    if ns:
        meta["namespace"] = ns
    return {"apiVersion": version, "kind": kind, "metadata": meta}


def render(cfg, inventory, versions):
    """EN: Convert validated inventory into desired objects without API calls.
    RU: Преобразовать проверенный inventory в целевые объекты без запросов API.

    Args:
        cfg (dict): Role settings / Настройки роли.
        inventory (dict): Validated grants / Проверенные назначения.
        versions (dict[str, str]): Kind-to-version mapping / Соответствие kind версиям API.

    Returns:
        tuple[dict, set]: Desired assignments and absent keys / Целевые назначения и ключи отсутствующих объектов.

    Raises:
        AccessError: Duplicate target objects or effective subjects / Повторяющиеся целевые объекты или субъекты.
    """
    desired, absent = {}, set()

    def add(obj, is_absent=False):
        key = identity(obj)
        require(key not in desired and key not in absent, "Two entries render the same API object")
        if is_absent:
            absent.add(key)
        else:
            desired[key] = obj

    for grant in inventory["grants"] or []:
        basic = grant["backend"] == "deckhouse"
        scope = grant["scope"]
        namespaces = scope.get("namespaces", [""])
        kind = (
            ("AuthorizationRule" if basic else "RoleBinding")
            if "namespaces" in scope
            else ("ClusterAuthorizationRule" if basic else "ClusterRoleBinding")
        )
        subjects = []
        for sub in grant.get("subjects", []):
            actual = copy.deepcopy(sub)
            if not basic and sub["kind"] != "ServiceAccount":
                actual["apiGroup"] = "rbac.authorization.k8s.io"
            subjects.append(actual)
        require(
            len({canonical(s) for s in subjects}) == len(subjects), "Duplicate effective subjects"
        )
        for ns in namespaces:
            name = grant.get("target_name") or generated_name(cfg, grant, kind, ns)
            obj = make(cfg, versions[kind], kind, name, ns, "grants", grant["id"])
            if grant.get("state") == "absent":
                add(obj, True)
                continue
            if basic:
                obj["spec"] = {
                    "subjects": sorted_items(subjects),
                    "accessLevel": grant["accessLevel"],
                    "portForwarding": grant.get("options", {}).get("portForwarding", False),
                    "allowScale": grant.get("options", {}).get("allowScale", False),
                }
                if "namespace_selector" in scope:
                    obj["spec"]["namespaceSelector"] = {
                        "labelSelector": copy.deepcopy(scope["namespace_selector"])
                    }
                elif scope.get("cluster") and scope["include_system_namespaces"]:
                    obj["spec"]["namespaceSelector"] = {"matchAny": True}
            else:
                obj["subjects"] = sorted_items(subjects)
                obj["roleRef"] = dict(grant["roleRef"], apiGroup="rbac.authorization.k8s.io")
            add(obj)
    return desired, absent


def clean(obj):
    """EN: Project allowlisted public fields while excluding passwords and arbitrary metadata.
    RU: Выбрать разрешённые публичные поля без паролей и произвольных metadata.

    Args:
        obj (dict | None): API object or absence / Объект API или отсутствие.

    Returns:
        dict | None: Independent sanitized projection / Отдельное представление без секретов.
    """
    if obj is None:
        return None
    result = {k: copy.deepcopy(obj[k]) for k in ("apiVersion", "kind") if k in obj}
    meta = obj.get("metadata", {})
    result["metadata"] = {
        k: meta[k] for k in ("name", "namespace", "uid", "resourceVersion") if k in meta
    }
    for k in ("subjects", "roleRef"):
        if k in obj:
            result[k] = copy.deepcopy(obj[k])
    if "spec" in obj:
        allowed = [
            "subjects",
            "accessLevel",
            "portForwarding",
            "allowScale",
            "namespaceSelector",
            "allowAccessToSystemNamespaces",
            "limitNamespaces",
            "additionalRoles",
        ]
        if obj.get("kind") == "User":
            allowed = ["email", "ttl", "groups", "userID"]
        elif obj.get("kind") == "Group":
            allowed = ["name", "members"]
        result["spec"] = {k: copy.deepcopy(v) for k, v in obj["spec"].items() if k in allowed}
    return result


def normalized(obj):
    """EN: Copy an object and normalize unordered membership and subject fields.
    RU: Скопировать объект и нормализовать неупорядоченные поля членства и субъектов.

    Args:
        obj (dict): API or desired object / Наблюдаемый или целевой объект.

    Returns:
        dict: Comparable copy with canonical subjects/members / Копия с нормализованными subjects/members для сравнения.
    """
    result = copy.deepcopy(obj)

    def subjects(items, rbac=False):
        for item in items:
            if item.get("kind") == "ServiceAccount":
                if item.get("apiGroup") == "":
                    item.pop("apiGroup")
            elif item.get("kind") in ("User", "Group"):
                if item.get("namespace") == "":
                    item.pop("namespace")
                if rbac:
                    item.setdefault("apiGroup", "rbac.authorization.k8s.io")
                elif item.get("apiGroup") in ("", "rbac.authorization.k8s.io"):
                    item.pop("apiGroup")
        return sorted_items(items)

    if "subjects" in result:
        result["subjects"] = subjects(result["subjects"], rbac=True)
    if "spec" in result:
        if "subjects" in result["spec"]:
            result["spec"]["subjects"] = subjects(result["spec"]["subjects"])
        if "members" in result["spec"]:
            result["spec"]["members"] = sorted_items(result["spec"]["members"])
    return result


def selector_matches(selector, labels):
    """EN: Evaluate a validated Kubernetes label selector.
    RU: Проверить соответствие проверенному селектору меток Kubernetes.

    Args:
        selector (dict): Validated selector / Проверенный селектор.
        labels (dict[str, str]): Namespace labels / Метки namespace.

    Returns:
        bool: Whether all selector conditions match / Выполняются ли все условия селектора.
    """
    if any(labels.get(k) != v for k, v in selector.get("matchLabels", {}).items()):
        return False
    for expr in selector.get("matchExpressions", []):
        key, op, values = expr["key"], expr["operator"], expr.get("values", [])
        if op == "In" and (key not in labels or labels[key] not in values):
            return False
        if op == "NotIn" and key in labels and labels[key] in values:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True
