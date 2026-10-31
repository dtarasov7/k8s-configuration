# Ansible-роль k8s-configuration: возможности и проект реализации

Статус: проект реализован в `roles/k8s-configuration/`; актуальный пользовательский контракт описан в README роли. Основание: `project.md`. Дата проверки документации: 23 октября 2026 года.

## 1. Назначение и границы

Роль декларативно управляет назначениями прав через Kubernetes REST API в vanilla Kubernetes и Deckhouse. Для Deckhouse дополнительно управляет локальными идентичностями User/Group. Один inventory может содержать назначения стандартного RBAC и базовой модели Deckhouse; backend выбирается отдельно для каждого назначения.

Результат работы — проверяемый план, применение изменений или экспорт существующих настроек. Роль не требует `kubernetes.core`, `kubectl` и установки агентов на узлах кластера.

В vanilla Kubernetes обычные пользователи и группы не являются API-объектами: роль только ссылается на идентичности, которые предоставляет настроенная аутентификация. Запись группы в inventory не создаёт членство в OIDC/LDAP и не добавляет группу в сертификат. Это принципиальное ограничение обещания «управлять пользователями» в исходном документе. [Kubernetes: authentication](https://kubernetes.io/docs/reference/access-authn-authz/authentication/)

| Возможность первой версии | Vanilla | Deckhouse |
| --- | --- | --- |
| RoleBinding / ClusterRoleBinding к существующим ролям | Да | Да |
| Ссылки на внешних User/Group | Да | Да |
| Создание локальных User/Group и изменение членства | Нет | Через user-authn |
| AuthorizationRule / ClusterAuthorizationRule | Нет | Через user-authz, базовая модель |
| Назначение существующих гранулярных ролей Deckhouse | Нет | Через backend `rbac` |
| Dry, apply, export, контроль владения и удаления | Да | Да |
| Динамический namespace selector | Нет в первой версии | Для ClusterAuthorizationRule при подтверждённой поддержке |

В первую версию не входят: управление AD/LDAP/OIDC-провайдерами, выпуск сертификатов пользователей, настройка API server, установка модулей Deckhouse, создание Namespace, Role/ClusterRole, ServiceAccount и токенов, ProjectRoleBinding, управление 2FA/сессиями. Существующий ServiceAccount можно использовать как субъект назначения. Изменение прав в приложениях, например Grafana, также находится вне области роли.

## 2. Исправления исходной проработки

| Положение project.md | Решение в проекте |
| --- | --- |
| «Ansible 2.12–3.12» | Не использовать как диапазон совместимости: различать пакет Ansible, ansible-core и Python; см. раздел 3 |
| Общие users/groups для двух платформ | Явно разделить внешние ссылки и локальные Deckhouse-идентичности |
| `users[].groups` и самостоятельные groups | Единственный источник членства — `groups[].members`; исключить противоречия двух списков |
| Для Deckhouse достаточно обнаружить CRD | Проверять API, схему, состояние модулей и необходимые настройки; CRD может оставаться после отключения модуля |
| Единственный переключатель basic/granular | Не запрещать их сосуществование; отдельно проверять доступность basic backend |
| Все изменения выполняются PATCH | Смена неизменяемого `roleRef` — операция replace |
| `prune: true` в примере по умолчанию | По умолчанию false, отдельно разрешать удаление идентичностей |
| Любой кластерный scope может исключать системные namespace | В RBAC это не реализуется ClusterRoleBinding; в Deckhouse нужны проверенные ограничения |
| Export готов к обратному импорту | Гарантировать это только для поддерживаемого подмножества; неподдерживаемое экспортировать как аудит |
| Права двух backend всегда складываются | Для vanilla RBAC — да; в Deckhouse учитывать версию и webhook |

`roleRef` у binding неизменяем; RoleBinding может ссылаться на Role своего namespace или ClusterRole, ClusterRoleBinding — только на ClusterRole. RBAC разрешения аддитивны, запретов в правилах нет. [Kubernetes: RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

В changelog Deckhouse описано изменение совместной работы CAR и независимого RBAC: ранее webhook мог запрещать доступ вне CAR даже при наличии binding. Поэтому упоминание «1.76.5» из исходника не принимается как достаточная граница совместимости: нужен проверенный профиль конкретного выпуска и интеграционный тест смешанных назначений. [Deckhouse: changelog 1.76](https://github.com/deckhouse/deckhouse/blob/main/CHANGELOG/CHANGELOG-v1.76.md)

## 3. Среда исполнения

Предлагаются два явно разделённых профиля:

| Профиль | Control node | Узел исполнения модуля |
| --- | --- | --- |
| Legacy для исходных ограничений | ansible-core 2.12, Python 3.8 | Тот же узел либо RED OS 7.3 с Python 3.8 |
| Предпочтительный при сохранении Python 3.8 на RED OS | ansible-core 2.19, Python 3.11–3.13 | RED OS 7.3, Python 3.8, отдельный execution host |

Это целевые профили тестирования, а не заявление о уже проверенной совместимости. При `connection: local` Python control node и интерпретатор модуля должны удовлетворять выбранному профилю; современный ansible-core нельзя просто запускать под Python 3.8. В матрице Ansible версия 2.19 поддерживает Python 3.8 на target, а 2.20 требует там минимум 3.9. Ветка 2.12 уже EOL. [Матрица Ansible](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html)

Для кода модуля сохраняется синтаксис Python 3.8. Перед реализацией фиксируются patch-версии ansible-core, Python и PyYAML для каждого профиля. RED OS проверяется фактическим запуском, а не предположением о совместимости с RHEL. Системные пакеты и Python роль автоматически не обновляет.

Один запуск обслуживает один кластер и одного владельца конфигурации. Playbook выполняется на одном execution host с доступом к API; запуск роли на каждом control-plane узле не нужен. Параллельные apply для одного owner/cluster запрещаются сериализацией CI.

## 4. Контракт inventory

Публичные переменные имеют префикс `k8s_configuration_`. Названия из `project.md` преобразуются так: `access_manager` → `k8s_configuration_config`, `access_users` → `k8s_configuration_users`, аналогично groups/grants/export. Не поддерживать два параллельных формата в первой версии.

Пример желаемой конфигурации Deckhouse:

```yaml
k8s_configuration_config:
  schema_version: 1
  mode: dry                     # dry | apply | export
  platform: deckhouse           # vanilla | deckhouse
  connection:
    kubeconfig: /etc/ansible/kubeconfigs/dkp-prod.yaml
    context: dkp-prod
    validate_tls: true
    timeout_seconds: 30
  deckhouse:
    basic_authz: true
    compatibility_profile: dkp-prod-validated
  management:
    owner: platform-team
    prune: false
    prune_identities: false
    adoption: []
  safety:
    max_deletions: 10
    allow_empty_desired: false
    allow_binding_replacement: false
    protected_namespaces: [kube-system, kube-public, kube-node-lease, default, loghouse]
    protected_namespace_prefixes: [kube-, d8-]
    allowed_protected_namespaces: []

k8s_configuration_users:
  - name: ivanov                  # metadata.name User CR
    source: static
    email: ivanov@example.org
    password_hash: "{{ vault_ivanov_bcrypt }}"
    password_policy: on_create  # on_create | managed

k8s_configuration_groups:
  - name: developers             # metadata.name Group CR
    source: static
    claim_name: developers      # значение группы в identity
    members: [ivanov]            # ссылки на users[].name

k8s_configuration_grants:
  - id: developers-edit
    backend: rbac
    subjects:
      - kind: Group
        source: static
        name: developers
    roleRef:
      kind: ClusterRole
      name: edit
    scope:
      namespaces: [application-dev, application-test]

  - id: payments-admin
    backend: deckhouse
    subjects:
      - kind: Group
        source: external
        name: K8S-Payments-Admins
    accessLevel: Admin
    scope:
      namespaces: [payments-prod]
    options:
      portForwarding: true
      allowScale: false

  - id: review-reader
    backend: deckhouse
    subjects:
      - kind: User
        source: static
        name: ivanov
    accessLevel: User
    scope:
      namespace_selector:
        matchLabels:
          environment: review
    options:
      portForwarding: false
      allowScale: false
```

Идентификатор compatibility_profile обозначает проверенный набор возможностей; его имя произвольно, но профиль должен быть определён и протестирован в реализации. Это не возможность обойти проверки кластера.

Для vanilla используются `platform: vanilla`, пустые users/groups и grants с `backend: rbac`. Для внешних субъектов `name` содержит точную строку после преобразований аутентификатора, включая настроенные префиксы. `source: external` заменяет частный случай `source: ad`: роль не проверяет наличие пользователя в каталоге. Пустой каталог пользователей не означает отсутствие допустимых внешних субъектов.

### Правила схемы

- `id` уникален; поля неизвестного назначения отвергаются, а не игнорируются.
- `subjects` — непустой список. Поддерживаются User, Group, ServiceAccount; для последнего обязательны namespace и `source: serviceaccount`.
- `source: static` требует соответствующей записи локального каталога и платформы Deckhouse. User разрешается в email, Group — в claim_name. В манифесте не сохраняется поле source: Kubernetes его не знает.
- Email локального пользователя задаётся в lowercase. Внешние имена не нормализуются произвольно. Проверяются коллизии фактических имён между локальными и внешними субъектами.
- `scope` содержит ровно один вариант: `cluster: true`, непустой список `namespaces` либо непустой `namespace_selector`. Пустой selector запрещён как неявный доступ ко всем namespace.
- `roleRef` разрешён только для rbac, `accessLevel/options` — только для deckhouse. Для Role проверяется существование в каждом namespace назначения.
- Namespace должны существовать. Роль не создаёт их и не изменяет метки.
- `state` по умолчанию present; `state: absent` задаёт явное удаление конкретного объекта в области владения. Для absent-grant сохраняются backend и scope для однозначного вычисления имён.
- Пропущенный раздел grants/users/groups означает «не управлять этим разделом»; явно заданный пустой список означает пустое desired state. При prune пустой desired требует `allow_empty_desired: true`.
- Управление членством группы авторитетное: список members полностью заменяет управляемое членство. Вложенные локальные группы в первой версии не поддерживаются.

## 5. Преобразование в Kubernetes-ресурсы

| Backend и scope | Объект и поля |
| --- | --- |
| rbac + cluster | Один ClusterRoleBinding, `roleRef` и `subjects` |
| rbac + namespaces | По RoleBinding на namespace |
| deckhouse + namespaces | По AuthorizationRule на namespace; `spec.subjects`, `spec.accessLevel`, `spec.portForwarding`, `spec.allowScale` |
| deckhouse + cluster | Один ClusterAuthorizationRule |
| deckhouse + namespace_selector | Один ClusterAuthorizationRule, selector в `spec.namespaceSelector.labelSelector` |
| static User | User: `spec.email`, `spec.password` при создании/явном управлении паролем |
| static Group | Group: `spec.name`, `spec.members` со ссылками на metadata.name пользователей |

Для basic backend AR допускает User, PrivilegedUser, Editor, Admin; CAR дополнительно ClusterEditor, ClusterAdmin, SuperAdmin. Selector может включать системные namespace; `matchAny` включает все. Namespace selector имеет приоритет над устаревшими limitNamespaces/allowAccessToSystemNamespaces. Проверять допустимость полей по установленной схеме. [Deckhouse: CR user-authz](https://deckhouse.io/modules/user-authz/cr.html)

API-версии AR v1alpha1 и CAR v1 — кандидаты профиля, а не универсальные константы. Для User документация описывает v1 и v1alpha1, для Group — v1alpha1. `User.spec.groups` устарел; членство следует задавать через Group. [Deckhouse: CR user-authn](https://deckhouse.io/modules/user-authn/cr.html)

Имена grants генерируются детерминированно из owner, grant id, kind и namespace: читаемый префикс плюс короткий SHA-256 с проверкой коллизий. Длина ограничивается требованиями ресурса; изменение списка namespace не переименовывает сохранившиеся объекты. User/Group используют явные имена inventory. Сортировка subjects/members и namespace делает diff стабильным.

### Системные namespace и динамические ограничения

Предлагаемый контракт для CAR с `scope.cluster`: обязательное поле `include_system_namespaces`. Значение false разрешается только в профиле, где подтверждено исключение системных namespace; true переводится в проверенную для профиля конфигурацию доступа ко всем namespace. При невозможности представить требование — ошибка. Для rbac это поле запрещено: ClusterRoleBinding не умеет исключать namespace.

Для namespace_selector роль не добавляет молча дополнительные условия. Если выбранные сейчас namespace пересекаются с защищёнными, требуется явное исключение в allowed_protected_namespaces. Проверка текущего набора не гарантирует безопасность будущих изменений labels: динамический selector должен отмечаться в плане как потенциальное расширение области доступа. Строгая изоляция требует явного списка namespace и отдельного контроля их меток.

В Deckhouse namespace-ограничения CAR требуют работающего multi-tenancy. Наличие CRD недостаточно; если режим выключен или его нельзя проверить, ограниченный CAR запрещается. Нельзя обещать изоляцию кластерных административных полномочий одним selector. [Deckhouse: FAQ](https://deckhouse.io/modules/user-authz/latest/faq.html)

Гранулярные роли назначаются обычными bindings через rbac. Список их имён и допустимый scope берётся из проверенного профиля: существование ClusterRole само по себе не означает допустимость ClusterRoleBinding для неё. Роль не переводит уровни Editor/Admin в гранулярные роли автоматически. [Deckhouse: использование user-authz](https://deckhouse.io/modules/user-authz/usage.html)

## 6. Dry, apply и export

### Plan

По умолчанию выполняются только чтение API и локальные вычисления. `apply` с Ansible `--check` выполняет тот же plan, без операций записи. Ansible `--diff` получает только очищенные различия.

План включает cluster identity, owner, версию схемы/профиля, create/update/delete/replace/noop, причины конфликтов и блокировок, прежний и новый scope, количество физических объектов. Удаления внутри replace входят в общий лимит. Производные объекты Deckhouse в список изменений не включаются.

Для изменения полномочий используется `privilege_change: increase | decrease | mixed | unknown`, а не обещание точного boolean-анализа. Изменение произвольной ClusterRole, её агрегации или группы внешнего IdP не всегда позволяет доказать отношение прав. Неизвестный результат не равен отсутствию повышения. Включение portForwarding, расширение scope и смена состава privileged-группы явно отмечаются.

Опциональный `server_validation` использует запросы с `dryRun=All`, когда поддерживаются API/admission. Он используется только перед настоящим apply; в dry/check даже эти POST/PATCH не выполняются. Проверка ресурса в ещё не существующей цепочке зависимостей может быть неполной. Серверная dry-run проверяет API/admission, но не будущую работу контроллера. [Kubernetes: API concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)

### Apply

1. Проверить схему inventory, соединение, совместимость, конфликты владения и весь план до первой записи.
2. Зафиксировать наблюдаемые UID/resourceVersion и отпечаток конфигурации кластера. Перепроверить предпосылки непосредственно перед изменением.
3. Создать/обновить User, затем Group, затем первичные назначения. Обработку паролей выполнять отдельно от публичного отчёта.
4. Выполнить разрешённые замены. Смена roleRef по умолчанию блокируется; при `allow_binding_replacement: true` использовать delete → дождаться удаления → create, отражая возможный перерыв доступа.
5. После успешного создания/обновления выполнить stale-prune назначений, затем изменения/удаления зависимых групп и пользователей. При state: absent identity сначала удалить её управляемые назначения и ссылки членства.
6. Дождаться наблюдаемого результата с timeout. Для Deckhouse применять доступные в профиле readiness/status-проверки; при их отсутствии проверять доступ отдельно и не подменять это наличием CR.
7. Вернуть выполненные и невыполненные операции, changed и ошибки. При частичном сбое остановиться, не выполнять дальнейший prune. Повторный запуск должен сходиться к desired state.

Операции нескольких ресурсов не транзакционны. Автоматического «отката всего» нет: он может восстановить отозванные права. Миграция backend по умолчанию создаёт новое назначение перед удалением старого и отмечает временное перекрытие. Для сценария, где перекрытие запрещено, применять явную двухэтапную миграцию с отзывом доступа сначала.

Обычный apply пересчитывает план. Для CI можно передать expected_plan_digest: он включает несекретное desired state, идентификатор кластера и наблюдаемые версии затрагиваемых объектов; любое расхождение требует нового плана. Значения секретов и их обычные хеши в публичный digest/отчёт не включаются; артефакт секретных входов CI фиксируется отдельно.

### Export

Режимы config.mode: `dry` (самостоятельный план), `apply`, `export`; `plan` остаётся совместимым синонимом dry. Dry читает кластер и выводит «Планируем добавить», «Планируем изменить», «Планируем удалить». Он не зависит от Ansible CLI-флагов. Apply --check прогнозирует изменения; --diff показывает очищенный before/after. Export --check читает фактическое состояние и проверяет запись файла, сохраняя режим export.

```yaml
k8s_configuration_export:
  mode: scoped                       # managed | scoped
  backends: [rbac, deckhouse]
  cluster_roles: [view, edit, platform-reader]
  roles:
    - namespace: application-dev
      name: application-developer
  access_levels: [User, Editor]
  namespaces: [application-dev, application-test]
  include_cluster_scoped: false
  exclude_controller_generated: true
  include_identities: true
  allow_partial: false
  destination: ./exports/dkp-prod.yaml
  audit_destination: ./exports/dkp-prod-audit.yaml
```

Managed выбирает ресурсы данного owner, включая ручные изменения. Scoped выбирает и ручные объекты по явным фильтрам. Фильтры действуют совместно; CAR экспортируется целиком с selector, namespace-фильтр не обрезает его смысл.

В destination сохранять непосредственно `k8s_configuration_users`, `k8s_configuration_groups`, `k8s_configuration_grants`, без обёртки inventory. Файл подключается через vars_files/group_vars или вставляется в vars inventory без правок. Конфигурацию соединения и Deckhouse profile задают отдельно для целевого кластера. Audit с UID/ownership/unsupported_fields хранится отдельно и не импортируется.

Выбранные самостоятельные User/Group и зависимости grants включаются в снимок. Для локального Deckhouse User сохранять bcrypt из API как password_hash: это позволяет создать его на другом кластере. Файл 0600, export всегда no_log и без diff содержимого; audit и консоль хешей не содержат. Перед хранением в Git использовать Ansible Vault. Токены, приватные ключи и сессии не экспортируются.

Неподдерживаемые поля/зависимости блокируют экспорт по умолчанию; allow_partial явно разрешает неполный снимок для аудита. Сохранять target_name для исходных имён. На исходном кластере unowned объекты требуют отдельного UID-bound adoption; export не захватывает владение. На целевом должны существовать Namespace и роли/ServiceAccount, на которые ссылаются grants; их определения эта роль не переносит.

## 7. Владение, удаление и защита от конфликтов

Объект идентифицируется по API group/resource, namespace, name; наблюдаемая incarnation — по UID. Предлагаемые метки: `access-manager.example.org/owner`, `access-manager.example.org/managed-by`; аннотации содержат grant id и schema version. Домен является примером, перед реализацией заменяется организационным и фиксируется. Метки не являются защитой от администратора кластера.

Правила обязательны независимо от режима:

- Объект с другим owner, без ownership или с признаками управления контроллером не изменяется.
- Признаки производного ресурса: ownerReferences, известные метки/аннотации Deckhouse и сведения проверенного профиля. Одного отсутствия ownerReferences недостаточно для adoption.
- Adoption допускается только по точному списку group/resource/namespace/name/uid, после проверки diff. Глобальное adopt_existing: true не поддерживается.
- Prune рассматривает только собственные первичные ресурсы в явно управляемых разделах и namespace. Ограниченный запуск не удаляет объекты за пределами области запуска.
- Ошибка discovery, 403, неполная пагинация, недоступный backend или ошибка любого обязательного чтения блокирует apply/prune. Это не «пустой список существующих объектов».
- Explicit absent и prune подчиняются одним ограничениям владения, лимитов и защищённых объектов. Удаление User/Group дополнительно требует prune_identities: true, включая explicit absent.
- Удаление identity блокируется, если остаются ссылки в доступных для проверки чужих назначениях или группах. При недостаточных правах проверки — ошибка. Даже полная проверка API не доказывает отсутствие внешних IdP-ссылок.
- DELETE содержит UID/resourceVersion preconditions; объект с изменившейся версией требует нового плана. При timeout проверить результат GET перед повтором. Finalizers не удалять принудительно.
- Поддерживать список защищённых объектов, включая binding исполнителя и аварийный доступ; полномочия исполнителя не включать в desired inventory этой же роли.

Коллизии локальных и внешних имён важны даже при разных source: Kubernetes видит конечную строку identity. Аннотация `user-authz.deckhouse.io/allow-authorization-rule-collision` разрешается только явно для конкретной локальной identity. Порядок User → Group → grants уменьшает конфликты первого запуска, но не заменяет проверку существующих правил. [Deckhouse: локальная аутентификация](https://deckhouse.io/modules/user-authn/usage.html)

Удаление User/Group или изменение членства не гарантирует немедленную инвалидизацию уже выданного токена. Срочный отзыв доступа требует удаления соответствующих назначений и учёта остальных источников прав; роль не обещает отзывать сессии IdP.

## 8. Устройство реализации

Предлагается один собственный Ansible-модуль и небольшое ядро без зависимостей от Kubernetes SDK. Не разбивать код на десятки файлов до появления реальной необходимости.

```text
roles/k8s-configuration/
  defaults/main.yml
  meta/main.yml
  handlers/main.yml
  tasks/
    main.yml
    pre-req.yml
    install.yml
    user.yml
    ssl.yml
    config.yml
    clean.yml
  library/k8s_configuration.py
  module_utils/access_manager/
    client.py
    schema.py
    render.py
    reconcile.py
    export.py
  templates/
  molecule/default/{molecule.yml,converge.yml,verify.yml}
  tests/unit/
  tests/integration/
  README.md
  README-en.md
  CHANGELOG.md
  CHANGELOG-en.md
```

Структура следует локальному шаблону роли; перечисленные пути сейчас не создаются. Имена задач начинаются с имени файла, переменные используют префикс роли. Системный пользователь, systemd и logrotate для API-клиента не нужны. Служебные файлы шаблона не должны устанавливать сервисы ради структуры.

`pre-req` выполняет проверки; `install` — проверку заранее подготовленных зависимостей и необходимых каталогов; `user` не создаёт Linux-пользователей; `ssl` готовит явно переданные локальные TLS-файлы, если это требуется; `config` вызывает модуль. `clean` с тегами never/clean удаляет только созданные ролью локальные артефакты и завершает play согласно шаблону. Удаление кластерных прав выполняется через обычный план absent/prune, а не отдельный обход проверок в clean. В plan/check подготовка каталогов и сертификатов не должна выполнять записи.

| Компонент | Ответственность |
| --- | --- |
| library | argument_spec, check mode, no_log-параметры, единый формат результата |
| client | kubeconfig, TLS/HTTP, discovery, пагинация, ошибки и ограниченные retry |
| schema | валидация inventory, нормализация identity, проверка возможностей |
| render | RBAC, Deckhouse authz и identity; чистые функции без HTTP |
| reconcile | ownership, diff, план, зависимости, preconditions, apply |
| export | фильтры, обратное преобразование, приватный inventory и отдельный audit |

### API-клиент

Базовый транспорт — стандартная библиотека Python (`urllib`, `ssl`, `json`) без requests; PyYAML нужен для безопасного чтения kubeconfig. Критические функции клиента тестируются отдельно. Использовать HTTPS с проверкой CA и hostname; endpoint задавать DNS-именем из сертификата.

Первая версия поддерживает один kubeconfig/context, bearer token/tokenFile и client certificate/key, включая data-поля. Относительные пути разрешаются относительно kubeconfig. Слияние KUBECONFIG, exec/auth-provider плагины, интерактивный OIDC refresh и impersonation исполнителя не поддерживаются: явная ошибка вместо частичного разбора. Секретные временные файлы — 0600 в каталоге 0700, удаление через finally; ошибки очистки отражаются без содержимого секрета. Не передавать credentials при redirect на другой origin.

Discovery определяет plural, scope и served versions. Профиль задаёт разрешённые версии/поля и проверенную семантику; не выбирать «самую новую» версию автоматически. Если CRD-схема недоступна, требуется заранее проверенный профиль и необходимые чтения ModuleConfig, иначе fail closed. Discovery не подтверждает работоспособность контроллера.

```text
GET    /version
GET    /api, /apis, /apis/{group}/{version}
GET    /apis/rbac.authorization.k8s.io/v1/rolebindings
GET    /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings
POST   /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings
PATCH  /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings/{name}
DELETE /apis/rbac.authorization.k8s.io/v1/namespaces/{ns}/rolebindings/{name}
```

Первый путь rolebindings — чтение по всем namespace; создавать namespaced объект через него нельзя. Для Deckhouse пути строятся из discovery аналогично.

Для обновлений предлагается JSON Patch с test resourceVersion/UID и точечными изменениями управляемых полей. Subject/member списки принадлежат роли целиком. Чужие labels/annotations и поля spec сохраняются, но неизвестные поля, влияющие на права, блокируют adoption. Удаление ранее управляемого optional-поля должно быть явным действием diff. ResourceVersion не участвует в семантическом сравнении, но участвует в защите записи.

GET-списки обходятся до конца через limit/continue. Retry с backoff разрешён для временных сетевых ошибок, 429 и выбранных 5xx; 401/403/422 завершают операцию. При неопределённом результате POST сначала GET детерминированного имени и проверка ownership/desired, при PATCH/DELETE — проверка состояния. Конфликт конкурентной записи останавливает применение устаревшего плана, а не вызывает force-update.

### Полномочия исполнителя

Нужны discovery и get/list управляемых ресурсов, Namespace, referenced Role/ClusterRole; для apply — create/patch/delete только выбранных видов. В Deckhouse дополнительно read CRD/ModuleConfig в соответствии с профилем. Право создавать binding само по себе недостаточно: Kubernetes проверяет права назначающего либо специальное bind. Не выдавать cluster-admin автоматически. Для необязательных SubjectAccessReview требуются отдельные права. [Kubernetes: ограничения назначения прав](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

### Секреты и отчёты

Пароли передаются уже подготовленным bcrypt-хешем; контракт password_hash принимает raw bcrypt, адаптер кодирует его в формат выбранного API. Соль/хеш не генерируются заново на каждом apply. `on_create` оставляет пароль существующего User без изменений; `managed` требует явно управляемого значения и проверки поведения целевой версии при смене пароля. UserOperation/принудительный reset в первую версию не входят.

Секреты разрешаются в переменных из Ansible Vault, внешнего secret store/HashiCorp Vault либо локальных файлов; lookup не встраивается в tasks или Python-клиент. HashiCorp lookup — необязательная зависимость окружения control node. TLS также принимает локальные пути или заранее разрешённое содержимое. Смена источника не меняет алгоритм роли.

Не выводить password/hash, Authorization headers, client keys, полный kubeconfig, секретные тела API и traceback с ними. Чувствительные аргументы модуля помечаются no_log, diff очищается до возврата Ansible. Отдельный публичный отчёт содержит только безопасные поля. Экспорт и отчёты по умолчанию 0600; записи файлов атомарные. Ошибки не подавлять пустым except/pass.

## 9. Проверка и критерии приёмки будущей роли

Документ не является результатом тестирования реализации. При разработке требуются следующие проверки:

| Уровень | Обязательные сценарии |
| --- | --- |
| Unit | схема, неизвестные поля, разрешение static/external, имена, selectors, canonical diff, secret redaction |
| API-клиент | TLS CA/hostname, tokenFile, относительные пути, пагинация, timeout после успешной записи, 403/409/422/429, concurrent update |
| Ownership | чужой объект, controller-owned без ownerReferences, adoption с неверным UID, пустое desired, выход за scope, лимит удалений |
| Vanilla integration | создание/изменение/отзыв bindings, roleRef replace, Role scope, повторный apply без изменений |
| Deckhouse integration | User/Group, AR/CAR, версии API, disabled module с сохранившимся CRD, multi-tenancy, смешанный RBAC/CAR, коллизии |
| Export | несколько subjects, selector без разворачивания, unsupported_fields, отсутствующие пароли, import/adoption без дублирования |
| Отказоустойчивость | обрыв API, частичный apply, перезапуск, недоступный контроллер; prune не продолжается после ошибки |
| Доступ | положительные и отрицательные запросы для конкретных identities, в разрешённых и запрещённых namespace |

Molecule использует Docker driver для execution environment, включая доступный RED OS 7.3-совместимый образ. Vanilla API поднимается отдельной тестовой оснасткой kind/k3s; kubectl в тестовой оснастке допустим, runtime роли от него не зависит. Deckhouse проверяется на настоящем выделенном стенде: установка одних CRD не тестирует контроллер/webhook. Для проверки деградации API нужен многоузловой стенд, но роль сама кластер не разворачивает. Systemd/privileged-контейнер не требуется, если в сценарии нет соответствующей зависимости.

Критерии готовности:

1. Во всех режимах кластера обращения проходят только через API, без kubernetes.core.
2. Dry/check/export не изменяют кластер; dry не выполняет mutating HTTP-запросы. Export по умолчанию включает собственные cluster-scoped назначения.
3. Повторный apply возвращает changed: false при неизменном desired state и отсутствии drift.
4. Чужие/производные ресурсы сохраняются; гонка UID/resourceVersion не приводит к перезаписи.
5. Реальный доступ соответствует ожиданиям, включая отрицательные тесты и задержки reconciliation.
6. Секреты отсутствуют в публичном выводе, diff и плане. Экспорт локального Deckhouse User содержит bcrypt только в приватном импортируемом файле, без вывода в audit/консоль.
7. Проходят unit/integration, `ansible-playbook --syntax-check`, `ansible-lint`, `molecule test` для утверждённых профилей.
8. README/CHANGELOG подготовлены на русском и английском, документированы все параметры, теги, inventory и сценарии тестирования.

## 10. Порядок реализации и оставшиеся вводные

Порядок: зафиксировать схему и fixtures → реализовать read-only client/discovery → renderer/plan и ownership → RBAC apply → Deckhouse identity/basic authz → export/adoption → интеграционные проверки и документация. Первый работающий срез — vanilla RBAC dry/apply без prune; удаление включать после тестов ограничений владения.

До объявления production-поддержки необходимо получить три набора вводных:

- Точные версии Kubernetes/Deckhouse, редакции, состояние user-authn/user-authz и multi-tenancy; по ним фиксируется профиль, включая coexistence-тест.
- Где обязателен Python 3.8: control node или только RED OS execution host; какой из профилей Ansible должен поддерживаться.
- Фактические username/group claims и префиксы, способ API-аутентификации исполнителя, границы owner и перечень защищённых назначений.

До получения этих данных архитектуру и unit-тесты можно разрабатывать, но нельзя заявлять подтверждённую совместимость с конкретным кластером. Проверенные веб-страницы Deckhouse помечены как документация невыпущенной версии; приведённые сведения требуют сопоставления с документацией установленного релиза и его API. Исходный `project.md` сохранён без изменений.
