"""EN: Execute Kubernetes operations through installed kubectl.
RU: Выполнять операции Kubernetes через установленный kubectl.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote, unquote, urlencode, urlsplit

from .schema import AccessError, require


class APIError(AccessError):
    """EN: Preserve API status while suppressing server response bodies.
    RU: Сохранять код API, скрывая содержимое ответа сервера.
    """
    def __init__(self, method, status):
        """EN: Build an API failure safe for Ansible output.
        RU: Создать ошибку API, безопасную для вывода Ansible.

        Args:
            method (str): Failed operation / Неуспешная операция.
            status (int): HTTP status inferred from kubectl / HTTP-код, определённый по kubectl.

        Returns:
            None: Sets status and the public message / Задаёт status и публичное сообщение.
        """
        self.status = status
        super().__init__(
            "Kubernetes API %s failed (HTTP %s); server body suppressed" % (method, status)
        )


# kubectl formats Kubernetes Status.reason as "Error from server (Reason): ...".
# Never expose arbitrary stderr: API responses and credential plugins can include secrets.
# RU: stderr API и credential-плагинов может содержать секреты; наружу передаётся только безопасный код.
STATUS_CODES = {
    "BadRequest": 400, "Unauthorized": 401, "Forbidden": 403, "NotFound": 404,
    "MethodNotAllowed": 405, "AlreadyExists": 409, "Conflict": 409,
    "RequestEntityTooLarge": 413, "UnsupportedMediaType": 415, "Invalid": 422,
    "TooManyRequests": 429, "InternalError": 500, "ServiceUnavailable": 503,
    "Timeout": 504, "ServerTimeout": 504,
}


class Client:
    """EN: Adapt API operations to kubectl with pinned context and private TLS files.
    RU: Адаптер API к kubectl с фиксированным контекстом и закрытыми TLS-файлами.
    """
    def __init__(self, connection):
        """EN: Resolve the kubeconfig context and prepare kubectl arguments.
        RU: Выбрать контекст kubeconfig и подготовить аргументы kubectl.

        Args:
            connection (dict): Validated connection and TLS settings / Проверенные параметры подключения и TLS.

        Returns:
            None: Initializes connection state / Инициализирует состояние подключения.

        Raises:
            AccessError: kubectl, kubeconfig or TLS setup fails / Ошибка настройки kubectl, kubeconfig или TLS.
        """
        self.connection = connection
        self.tempdir = None
        self.resources = {}
        self.cleanup_warnings = []
        try:
            self._load()
        except Exception:
            self.close()
            raise

    def _materialize(self, content):
        """EN: Write TLS content or a manifest into a private temporary file.
        RU: Записать TLS-данные или манифест в закрытый временный файл.

        Args:
            content (bytes): File contents / Содержимое файла.

        Returns:
            str: Path to a mode-0600 file / Путь к файлу с правами 0600.

        Raises:
            OSError: Temporary file creation or writing fails / Ошибка создания или записи файла.
        """
        fd, path = tempfile.mkstemp(dir=self.tempdir)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        return path

    def _run(self, args, method, body=None):
        """EN: Run kubectl without a shell and decode its JSON response.
        RU: Запустить kubectl без shell и разобрать JSON-ответ.

        Args:
            args (list[str]): Operation arguments / Аргументы операции.
            method (str): Safe diagnostic label / Безопасное имя операции.
            body (dict | list | None): JSON payload sent via stdin / JSON-тело для stdin.

        Returns:
            dict | list: Decoded JSON; {} for empty output / Разобранный JSON; {} при пустом выводе.

        Raises:
            AccessError: Execution, timeout, API or JSON failure / Ошибка запуска, таймаут, ошибка API или JSON.
        """
        # Always close stdin after the payload; plugins must not prompt on a terminal.
        # RU: Закрытый stdin исключает интерактивный запрос credentials во время Ansible-запуска.
        data = json.dumps(body).encode("utf-8") if body is not None else b""
        try:
            result = subprocess.run(
                self.argv + args, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=self.connection["timeout_seconds"], check=False,
            )
        except FileNotFoundError:
            raise AccessError("kubectl executable not found on the execution host") from None
        except subprocess.TimeoutExpired:
            raise AccessError("kubectl timed out during " + method) from None
        except OSError:
            raise AccessError("Cannot execute kubectl on the execution host") from None
        if result.returncode:
            reason = re.search(rb"Error from server \(([A-Za-z]+)\):", result.stderr)
            status = STATUS_CODES.get(reason[1].decode("ascii")) if reason else None
            if b"You must be logged in to the server (Unauthorized)" in result.stderr:
                status = 401
            if status:
                raise APIError(method, status)
            raise AccessError(
                "kubectl failed during %s; check kubeconfig, context, credentials/plugins, "
                "TLS and API connectivity on the execution host; output suppressed" % method
            )
        try:
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except (ValueError, UnicodeError):
            raise AccessError("kubectl returned invalid JSON during " + method) from None

    def _load(self):
        """EN: Validate the selected endpoint and pin context/TLS arguments.
        RU: Проверить выбранный endpoint и зафиксировать аргументы контекста/TLS.

        Returns:
            None: Populates argv and private temporary paths / Заполняет argv и временные пути.

        Raises:
            AccessError: Missing context, unsafe endpoint or conflicting TLS policy / Нет контекста, небезопасный endpoint или конфликт TLS-политики.
        """
        path = os.path.abspath(os.path.expanduser(self.connection["kubeconfig"]))
        self.tempdir = tempfile.mkdtemp(prefix="k8s-access-")
        os.chmod(self.tempdir, 0o700)
        self.argv = [
            self.connection.get("kubectl", "kubectl"), "--kubeconfig=" + path,
            "--request-timeout=%ss" % self.connection["timeout_seconds"],
            "--cache-dir=" + self.tempdir, "--v=0",
        ]
        context = self.connection.get("context")
        if context:
            self.argv.append("--context=" + context)
        # kubectl owns kubeconfig parsing, relative paths, credential plugins and TLS.
        # No --raw: this local command must not return credential material.
        doc = self._run(["config", "view", "--minify", "--output=json"], "config view")
        require(isinstance(doc, dict), "Invalid kubectl config view response")
        clusters = doc.get("clusters", [])
        require(len(clusters) == 1, "Kubeconfig must select one cluster")
        cluster = clusters[0].get("cluster", {})
        uri = urlsplit(cluster.get("server", ""))
        require(
            uri.scheme == "https" and uri.hostname and not uri.username
            and not uri.password and not uri.query and not uri.fragment,
            "API server must be an HTTPS URL without credentials/query",
        )
        # Pin the resolved context for every request, even when current-context was used.
        # RU: Последующие вызовы используют тот же контекст, даже если current-context изменится.
        context = context or doc.get("current-context")
        require(isinstance(context, str) and bool(context), "Kubeconfig context is missing")
        if not self.connection.get("context"):
            self.argv.append("--context=" + context)
        validate = self.connection["validate_tls"]
        require(
            not (validate and cluster.get("insecure-skip-tls-verify")),
            "Insecure kubeconfig requires explicit connection.validate_tls: false",
        )
        self.argv.append("--insecure-skip-tls-verify=" + str(not validate).lower())
        for key, flag in (
            ("ca_content", "certificate-authority"),
            ("cert_content", "client-certificate"),
            ("key_content", "client-key"),
        ):
            if key in self.connection:
                content = self.connection[key]
                require(isinstance(content, str) and bool(content), "Empty TLS content")
                self.argv.append("--%s=%s" % (flag, self._materialize(content.encode("utf-8"))))

    def close(self):
        """EN: Remove temporary files and retain cleanup failures as warnings.
        RU: Удалить временные файлы и сохранить ошибки очистки как предупреждения.

        Returns:
            None: Updates cleanup_warnings if needed / При необходимости обновляет cleanup_warnings.
        """
        if self.tempdir:
            try:
                shutil.rmtree(self.tempdir)
            except OSError:
                self.cleanup_warnings.append("Could not remove temporary kubectl directory")
            self.tempdir = None

    def _patch_manifest(self, path):
        """EN: Resolve a discovered object path into a minimal patch manifest.
        RU: Преобразовать путь обнаруженного объекта в минимальный манифест для patch.

        Args:
            path (str): Absolute Kubernetes API path / Абсолютный путь Kubernetes API.

        Returns:
            dict: API version, kind and identity / Версия API, kind и идентификатор.

        Raises:
            AccessError: Path matches no discovered resource / Путь не соответствует обнаруженным ресурсам.
        """
        # A minimal versioned manifest makes kubectl patch select the discovered API
        # version, including Deckhouse CRDs and legacy names containing colons.
        # RU: Версию patch задаёт discovery, а не догадка kubectl по имени ресурса.
        for kind, resource in self.resources.items():
            prefix = resource["base"] + "/"
            if not path.startswith(prefix):
                continue
            parts = path[len(prefix):].split("/")
            if resource["namespaced"] and len(parts) == 4 and parts[0] == "namespaces":
                plural, name = parts[2:]
                meta = {"name": unquote(name), "namespace": unquote(parts[1])}
            elif not resource["namespaced"] and len(parts) == 2:
                plural, name = parts
                meta = {"name": unquote(name)}
            else:
                continue
            if plural == resource["plural"]:
                return {"apiVersion": resource["apiVersion"], "kind": kind, "metadata": meta}
        raise AccessError("PATCH path does not match a discovered resource")

    def request(self, method, path, body=None, query=None):
        """EN: Execute one API operation; retry only transient GET failures.
        RU: Выполнить операцию API; повторять только временные ошибки GET.

        Args:
            method (str): GET, POST, PATCH or DELETE / Метод GET, POST, PATCH или DELETE.
            path (str): Absolute API path / Абсолютный путь API.
            body (dict | list | None): Manifest or JSON Patch / Манифест или JSON Patch.
            query (dict | None): URL options; PATCH supports dryRun only / Параметры URL; PATCH поддерживает только dryRun.

        Returns:
            dict | list: Decoded response / Разобранный ответ.

        Raises:
            AccessError: Unsupported request or exhausted kubectl/API failure / Неподдерживаемый запрос или ошибка kubectl/API после повторов.
        """
        require(path.startswith("/") and not path.startswith("//"), "Invalid API path")
        require(method in ("GET", "POST", "PATCH", "DELETE"), "Unsupported Kubernetes operation")
        url = path + ("?" + urlencode(query) if query else "")
        manifest_path = None
        if method == "PATCH":
            manifest = self._patch_manifest(path)
            manifest_path = self._materialize(json.dumps(manifest).encode("utf-8"))
            args = ["patch", "--filename=" + manifest_path, "--type=json",
                    "--patch-file=/dev/stdin", "--output=json"]
            if "namespace" in manifest["metadata"]:
                args.append("--namespace=" + manifest["metadata"]["namespace"])
            require(not query or query == {"dryRun": "All"}, "Unsupported PATCH query")
            if query:
                args.append("--dry-run=server")
        else:
            args = [{"GET": "get", "POST": "create", "DELETE": "delete"}[method], "--raw=" + url]
            if body is not None:
                args.append("--filename=-")
        try:
            # EN: Retrying writes may duplicate a committed request whose response was lost.
            # RU: Повтор записи опасен: сервер мог применить запрос до потери ответа.
            for attempt in range(self.connection["retries"] + 1):
                try:
                    return self._run(args, method, body)
                except AccessError as exc:
                    transient = not isinstance(exc, APIError) or exc.status in (429, 500, 502, 503, 504)
                    if method != "GET" or not transient or attempt == self.connection["retries"]:
                        raise
                    time.sleep(min(2**attempt, 4))
        finally:
            if manifest_path:
                os.unlink(manifest_path)

    def get(self, path, missing=False):
        """EN: Read an object and optionally treat HTTP 404 as absence.
        RU: Прочитать объект и при необходимости считать HTTP 404 отсутствием.

        Args:
            path (str): Object API path / Путь объекта в API.
            missing (bool): Return None for HTTP 404 / Вернуть None при HTTP 404.

        Returns:
            dict | None: Object or allowed absence / Объект или допустимое отсутствие.

        Raises:
            AccessError: API failure other than allowed absence / Ошибка API, не являющаяся допустимым отсутствием.
        """
        try:
            return self.request("GET", path)
        except APIError as exc:
            if exc.status == 404 and missing:
                return None
            raise

    def list(self, path, query=None):
        """EN: Read every page of a Kubernetes collection.
        RU: Прочитать все страницы коллекции Kubernetes.

        Args:
            path (str): Collection API path / Путь коллекции в API.
            query (dict | None): Optional selectors / Необязательные селекторы.

        Returns:
            list[dict]: All collection items / Все объекты коллекции.

        Raises:
            AccessError: API failure, malformed page or repeated token / Ошибка API, неверная страница или повтор токена.
        """
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
            # EN: Repeated tokens indicate an incomplete read, never a valid empty tail.
            # RU: Повтор токена означает неполное чтение, а не допустимый конец коллекции.
            require(token not in tokens, "Repeated pagination token")
            tokens.add(token)
            query["continue"] = token

    def discover(self, api_version, kind, namespaced):
        """EN: Discover and cache one readable resource with the expected scope.
        RU: Обнаружить и запомнить читаемый ресурс с ожидаемой областью действия.

        Args:
            api_version (str): Served version such as deckhouse.io/v1 / Обслуживаемая версия, например deckhouse.io/v1.
            kind (str): Kubernetes kind / Kind Kubernetes.
            namespaced (bool): Expected resource scope / Ожидается ли namespace-ресурс.

        Returns:
            None: Registers metadata in resources / Сохраняет сведения в resources.

        Raises:
            AccessError: Resource is absent, ambiguous, unreadable or has wrong scope / Ресурс отсутствует, неоднозначен, недоступен или имеет другую область.
        """
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
        """EN: Build an escaped collection or object path for a discovered kind.
        RU: Собрать экранированный путь коллекции или объекта обнаруженного kind.

        Args:
            kind (str): Previously discovered kind / Ранее обнаруженный kind.
            namespace (str | None): Namespace when applicable / Namespace при необходимости.
            name (str | None): Object name; None selects collection / Имя объекта; None выбирает коллекцию.

        Returns:
            str: Absolute API path / Абсолютный путь API.

        Raises:
            AccessError: Namespace conflicts with resource scope / Namespace несовместим с областью ресурса.
            KeyError: Kind was not discovered / Kind ещё не обнаружен.
        """
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
