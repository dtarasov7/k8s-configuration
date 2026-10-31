"""Kubeconfig, HTTPS transport, discovery and complete list reads."""
import base64
import json
from http.client import HTTPException
import os
import shutil
import ssl
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from .schema import AccessError, require, mapping


class APIError(AccessError):
    def __init__(self, method, status):
        self.status = status
        super().__init__(
            "Kubernetes API %s failed (HTTP %s); server body suppressed" % (method, status)
        )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccessError("API redirects are forbidden")


class Client:
    def __init__(self, connection):
        self.connection = connection
        self.tempdir = None
        self.resources = {}
        self.cleanup_warnings = []
        try:
            self._load()
        except Exception:
            self.close()
            raise

    def _file(self, path):
        return path if os.path.isabs(path) else os.path.join(self.base, path)

    def _materialize(self, content):
        if self.tempdir is None:
            self.tempdir = tempfile.mkdtemp(prefix="k8s-access-")
            os.chmod(self.tempdir, 0o700)
        fd, path = tempfile.mkstemp(dir=self.tempdir)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        return path

    def _tlsfile(self, obj, key, content_key):
        content = self.connection.get(content_key)
        if content is not None:
            require(isinstance(content, str) and bool(content), "Empty TLS content")
            return self._materialize(content.encode("utf-8"))
        if key + "-data" in obj:
            try:
                data = base64.b64decode(obj[key + "-data"], validate=True)
            except (ValueError, TypeError):
                raise AccessError("Invalid kubeconfig certificate data") from None
            return self._materialize(data)
        return self._file(obj[key]) if key in obj else None

    def _load(self):
        try:
            import yaml
        except ImportError:
            raise AccessError("PyYAML is required on the execution host") from None
        path = os.path.abspath(os.path.expanduser(self.connection["kubeconfig"]))
        self.base = os.path.dirname(path)
        try:
            with open(path, encoding="utf-8") as stream:
                doc = yaml.safe_load(stream)
        except (OSError, ValueError, yaml.YAMLError):
            raise AccessError("Cannot read or parse kubeconfig") from None
        try:
            require(isinstance(doc, dict), "Invalid kubeconfig")
            require(not doc.get("extensions"), "Kubeconfig extensions are unsupported")
            context = self.connection.get("context") or doc.get("current-context")
            contexts = [v["context"] for v in doc["contexts"] if v["name"] == context]
            require(len(contexts) == 1, "Kubeconfig context is missing or ambiguous")
            ctx = contexts[0]
            clusters = [v["cluster"] for v in doc["clusters"] if v["name"] == ctx["cluster"]]
            users = [v["user"] for v in doc.get("users", []) if v["name"] == ctx.get("user")]
            require(
                len(clusters) == len(users) == 1, "Kubeconfig cluster/user is missing or ambiguous"
            )
            cluster, user = clusters[0], users[0]
            mapping(
                cluster,
                [
                    "server",
                    "certificate-authority",
                    "certificate-authority-data",
                    "insecure-skip-tls-verify",
                ],
                "kubeconfig cluster",
                ["server"],
            )
            mapping(
                user,
                [
                    "token",
                    "tokenFile",
                    "client-certificate",
                    "client-certificate-data",
                    "client-key",
                    "client-key-data",
                ],
                "kubeconfig user",
            )
            self.server = cluster["server"].rstrip("/")
            uri = urlsplit(self.server)
            require(
                uri.scheme == "https"
                and uri.hostname
                and not uri.username
                and not uri.password
                and not uri.query
                and not uri.fragment,
                "API server must be an HTTPS URL without credentials/query",
            )
            validate = self.connection["validate_tls"]
            require(
                not (validate and cluster.get("insecure-skip-tls-verify")),
                "Insecure kubeconfig requires explicit connection.validate_tls: false",
            )
            ca = self._tlsfile(cluster, "certificate-authority", "ca_content")
            ctx_ssl = (
                ssl.create_default_context(cafile=ca)
                if validate
                else ssl._create_unverified_context()
            )
            cert = self._tlsfile(user, "client-certificate", "cert_content")
            key = self._tlsfile(user, "client-key", "key_content")
            require(bool(cert) == bool(key), "Both client certificate and key are required")
            if cert:
                ctx_ssl.load_cert_chain(cert, key)
            self.token = user.get("token")
            self.token_file = self._file(user["tokenFile"]) if "tokenFile" in user else None
            require(not (self.token and self.token_file), "Choose token or tokenFile")
            require(
                bool(self.token or self.token_file or cert),
                "No supported credentials in kubeconfig",
            )
            self.opener = build_opener(NoRedirect(), HTTPSHandler(context=ctx_ssl))
        except AccessError:
            raise
        except (KeyError, TypeError, ValueError, OSError, ssl.SSLError):
            raise AccessError("Invalid kubeconfig or TLS material; details suppressed") from None

    def close(self):
        if self.tempdir:
            try:
                shutil.rmtree(self.tempdir)
            except OSError:
                self.cleanup_warnings.append("Could not remove temporary TLS directory")
            self.tempdir = None

    def request(self, method, path, body=None, query=None):
        require(path.startswith("/") and not path.startswith("//"), "Invalid API path")
        token = self.token
        if self.token_file:
            try:
                with open(self.token_file, encoding="utf-8") as stream:
                    token = stream.read().strip()
            except OSError:
                raise AccessError("Cannot read tokenFile") from None
            require(bool(token), "tokenFile is empty")
        headers = {"Accept": "application/json"}
        if token:
            require(
                isinstance(token, str) and "\n" not in token and "\r" not in token,
                "Invalid bearer token",
            )
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = (
                "application/json-patch+json" if method == "PATCH" else "application/json"
            )
        url = self.server + path + ("?" + urlencode(query) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(self.connection["retries"] + 1):
            try:
                req = Request(url, data=data, headers=headers, method=method)
                with self.opener.open(req, timeout=self.connection["timeout_seconds"]) as response:
                    payload = response.read()
                return json.loads(payload) if payload else {}
            except HTTPError as exc:
                status = exc.code
                exc.close()
                if (
                    method == "GET"
                    and status in (429, 500, 502, 503, 504)
                    and attempt < self.connection["retries"]
                ):
                    time.sleep(min(2**attempt, 4))
                    continue
                raise APIError(method, status) from None
            except (URLError, OSError, HTTPException):
                if method == "GET" and attempt < self.connection["retries"]:
                    time.sleep(min(2**attempt, 4))
                    continue
                raise AccessError("Kubernetes transport failed during " + method) from None
            except (ValueError, TypeError):
                raise AccessError("Kubernetes API returned invalid JSON") from None

    def get(self, path, missing=False):
        try:
            return self.request("GET", path)
        except APIError as exc:
            if exc.status == 404 and missing:
                return None
            raise

    def list(self, path, query=None):
        query = dict(query or {})
        query["limit"] = 500
        items, tokens = [], set()
        while True:
            doc = self.request("GET", path, query=query)
            require(
                isinstance(doc, dict) and isinstance(doc.get("items"), list),
                "Invalid API list response",
            )
            items.extend(doc["items"])
            token = doc.get("metadata", {}).get("continue")
            if not token:
                return items
            require(token not in tokens, "Repeated pagination token")
            tokens.add(token)
            query["continue"] = token

    def discover(self, api_version, kind, namespaced):
        base = "/api/" + api_version if "/" not in api_version else "/apis/" + api_version
        doc = self.get(base)
        candidates = [
            r
            for r in doc.get("resources", [])
            if r.get("kind") == kind and "/" not in r.get("name", "")
        ]
        require(
            len(candidates) == 1 and candidates[0].get("namespaced") is namespaced,
            "Required API resource is not available: " + kind,
        )
        resource = candidates[0]
        require(
            {"get", "list"} <= set(resource.get("verbs", [])), "Resource cannot be read: " + kind
        )
        self.resources[kind] = {
            "apiVersion": api_version,
            "base": base,
            "plural": resource["name"],
            "namespaced": namespaced,
            "verbs": resource.get("verbs", []),
        }

    def path(self, kind, namespace=None, name=None):
        resource = self.resources[kind]
        path = resource["base"]
        if namespace:
            require(resource["namespaced"], "Unexpected namespace for " + kind)
            path += "/namespaces/" + quote(namespace, safe="")
        path += "/" + resource["plural"]
        if name:
            require(not resource["namespaced"] or namespace, "Namespaced object requires namespace")
            path += "/" + quote(name, safe="")
        return path
