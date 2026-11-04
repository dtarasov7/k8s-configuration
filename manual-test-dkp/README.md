# Ручная проверка назначения прав на Deckhouse CE/OSS 1.73.4

Команды Ansible выполняются из корня проекта. Целевой сервер — `dkp`, одноузловой Deckhouse. `playbook.yaml` содержит только вызов роли, данные находятся в `inventory/group_vars/access_test_dkp/k8s-config.yml`.

Для существующего OpenLDAP на `redos8:389` см. [полную инструкцию Dex → OpenLDAP](OPENLDAP.md): поиск пользователей и групп, пароль bind-учётки, вход и получение kubeconfig, назначение прав группе `developers` и пользователю `alice`, проверка доступа и точечный отзыв. Шаблон провайдера — [openldap-dex-provider.yml.example](manifests/openldap-dex-provider.yml.example); пароль в репозиторий не записывается.

## Разделение ответственности

**Манифесты создают окружение, Ansible назначает права существующим субъектам.**

| Что | Кто создаёт и изменяет |
| --- | --- |
| Namespace, Role, ClusterRole, ServiceAccount, ConfigMap, тестовый Deployment | `kubectl apply -f manifests/fixtures.yml` |
| Локальные Deckhouse User и Group | Тот же `fixtures.yml` |
| Пользователи и группы LDAP | Внешний LDAP; в примере используются вымышленные claims |
| RoleBinding / ClusterRoleBinding | Роль Ansible |
| AuthorizationRule | Роль Ansible, только сценарий `basic-namespaced.yml` |

Роль не управляет User/Group ни в одном режиме; дополнительные переключатели для этого не нужны.

В subjects используются kind и точное name, получаемое Kubernetes. Для локального пользователя это spec.email, для локальной группы — spec.name, а не metadata.name. LDAP claims также передаются буквально.

Роль не создаёт Role/ClusterRole: она проверяет существование roleRef и использует готовые роли. Стандартные view/edit/admin должны уже присутствовать в кластере, дополнительные роли находятся в fixtures. Пользователями и составом групп управляет внешний механизм.

## Состав окружения

```text
manual-test-dkp/
├── playbook.yaml
├── inventory/
│   ├── hosts.ini
│   └── group_vars/access_test_dkp/k8s-config.yml
├── manifests/
│   ├── fixtures.yml
│   ├── manual-binding.yml
│   └── selector-extra.yml
├── scenarios/
├── output/                    # Результаты на Ansible controller
└── README.md
```

`fixtures.yml` создаёт **16 локальных User и 4 Group**: 10 пользователей и 3 группы основного набора, ещё 6 пользователей и группа для необязательного native AuthorizationRule. Общий пароль всех локальных тестовых пользователей — **`12121212`**. В манифесте хранится Base64 от bcrypt-хеша; отдельный `test-user.bcrypt` больше не требуется. Это публичные тестовые credentials. Настройки парольной политики Deckhouse не меняются; вход может потребовать смены пароля/2FA.

Формат проверен по CRD версии 1.73.4: [User](https://raw.githubusercontent.com/deckhouse/deckhouse/v1.73.4/modules/150-user-authn/crds/user.yaml), [Group](https://raw.githubusercontent.com/deckhouse/deckhouse/v1.73.4/modules/150-user-authn/crds/group.yaml).

Локальные имена: metadata.name пользователя `dkp-access-<имя>`, email `dkp-access-<имя>@example.invalid`. Группы: metadata.name `dkp-access-readers`, `dkp-access-editors`, `dkp-access-unused`, `dkp-access-basic-readers`; claims соответственно `dkp-access:readers`, `dkp-access:editors`, `dkp-access:unused`, `dkp-access:basic-readers`.

Базовый запуск создаёт RoleBinding по списку `manual_dkp_grants_baseline`:

| Субъект / группа | Назначение |
| --- | --- |
| alice / dkp-access:readers | view в dev/stage, без Secrets и записи |
| bob / dkp-access:editors | edit в dev, включая Secrets; изоляция stage |
| auditor | Чтение pods/log без exec в dev |
| privileged | Secrets и pods/exec только в stage |
| selector | view по явному списку dev/stage |
| scaler | Чтение Deployment и deployments/scale в dev |
| forwarder | pods/portforward в dev без exec |
| admin | Стандартная admin в stage без удаления Namespace |
| temporary | view в stage для absent/prune/replace |
| standalone / dkp-access:unused | Исходно без назначений; сценарии update/group-binding |
| ldap:dkp-access:node-readers | Чтение nodes на уровне кластера |
| ldap-test-reader@example.invalid | view только в dev |
| ldap:dkp-access:readers | view в dev/stage |
| ldap:dkp-access:deployers | Role для deployments в dev, без Secrets |
| ldap-test-auditor@example.invalid | Только get ConfigMap public-config в stage |

LDAP-имена вымышлены. Создание bindings не требует существования таких записей в LDAP. Для настоящего входа замените имена на реальные claims LDAP-коннектора. LDAP-пользователи/группы не создаются как Deckhouse User/Group.

## Подключение

В `inventory/hosts.ini` группа `access_test_dkp` и единственный узел `dkp`; исправьте адрес, SSH-пользователя и Python при необходимости. В inventory задано `ansible_become: true`; если sudo требует пароль, добавьте `-K`.

На выбранном узле нужны Python >=3.8, kubectl и административный kubeconfig. По умолчанию:

```yaml
manual_dkp_kubeconfig: /etc/kubernetes/admin.conf
manual_dkp_kubectl: kubectl
manual_dkp_mode: dry
```

Выбор контекста: `k8s_configuration_config_connection_context`; current-context не изменяется. Kubectl выполняется на выбранном target host, файлы результатов сохраняются на контроллере.

Для создания fixtures нужны обслуживаемые User v1 и Group v1alpha1, включённый user-authn. Для применения прав нужен готовый user-authz и соответствующие API/CRD. Наличие ModuleConfig не обязательно при готовом Module; существующий ModuleConfig со spec.enabled=false блокирует работу. Стенд не включает модули и не меняет их настройки.

Диагностика на dkp:

```bash
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf get modules user-authn user-authz
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf -n d8-user-authn get deployment dex
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf get crd users.deckhouse.io groups.deckhouse.io \
  authorizationrules.deckhouse.io clusterauthorizationrules.deckhouse.io
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf get clusterroles view edit admin
```

## Подготовка окружения

Скопируйте манифесты на dkp (замените SSH-пользователя при необходимости):

```bash
scp -r manual-test-dkp/manifests root@dkp:/tmp/k8s-access-dkp-manifests
```

На dkp:

```bash
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf apply -f /tmp/k8s-access-dkp-manifests/fixtures.yml
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf get users.deckhouse.io -l purpose=k8s-configuration-manual-dkp
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf get groups.deckhouse.io -l purpose=k8s-configuration-manual-dkp
```

Файл создаёт все дополнительные Role/ClusterRole, namespace и локальные идентичности сразу. Он не создаёт bindings, AuthorizationRule, LDAP-коннектор или LDAP-записи. Не применяйте целиком каталог manifests: manual-binding и selector-extra используются только в отдельных сценариях. Повторное применение fixtures возвращает пароль/состав локальных групп к исходным тестовым значениям.

При переходе со старого стенда уже созданные локальные пользователи/группы продолжают существовать. Новое inventory их не изменяет и не удаляет, даже если остались старые ownership labels. Для native-сценария в User заранее указана явная аннотация allow-authorization-rule-collision: повторная подготовка после создания AR намеренно допускает совпадение локального email с AR subject.

## Dry, check и apply

```bash
# По умолчанию dry: план без изменения API, сохраняется output/dkp/dry.yml.
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp
# Обычный Ansible check поверх apply; файлы результатов не записываются.
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e manual_dkp_mode=apply --check --diff
# Назначение прав.
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e manual_dkp_mode=apply
# Повтор: без изменений при неизменном состоянии кластера.
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e manual_dkp_mode=apply
```

Dry/apply не читают файлы паролей. для реального exec/port-forward нужен работающий Pod, fixtures содержат Deployment с replicas=0.

## Дополнительные сценарии

```bash
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/group-binding.yml
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/group-binding.yml -e manual_dkp_mode=apply
```

| Файл scenarios | Проверка |
| --- | --- |
| baseline.yml | Базовый набор назначений |
| openldap.yml | Baseline + Group developers: view в dev; User alice: get ConfigMap public-config в stage. Реальные claims можно переопределить |
| openldap-absent.yml | Отзыв только двух назначений openldap.yml через state: absent; baseline сохраняется |
| group-binding.yml | Замена subject у audit-logs на существующую локальную группу unused и вымышленную LDAP-группу auditors; состав групп не меняется |
| update.yml | Замена auditor на существующего standalone в RoleBinding |
| absent.yml / prune.yml | Отзыв temporary-reader явно либо через prune |
| replace.yml | Замена immutable roleRef view → edit; требует `-e manual_dkp_allow_replacement=true` |
| rbac.yml | Прямые внешние User, ServiceAccount, cross-namespace SA, resourceNames и ClusterRoleBinding node-reader |
| basic-namespaced.yml | 6 AuthorizationRule для готовых локальных identities: User/PrivilegedUser/Editor/Admin, allowScale и portForwarding |
| deckhouse-rbac.yml | Готовая d8:use:role:viewer; сначала проверьте существование ClusterRole |
| ce-selector-refused.yml | Ожидаемый отказ CAR selector без подтверждённого enableMultiTenancy=true; в CE стенд эту возможность не включает |
| protected.yml | Ожидаемый отказ для защищённого namespace default |
| empty-guard.yml / deletion-limit.yml | Ожидаемые защитные отказы после baseline |
| adopt.yml | Принятие ручного RoleBinding по точному UID |
| export-scoped.yml | Ограниченный снимок dev/stage |
| cleanup.yml | Отзыв только собственных grants, без удаления User/Group/Role/ClusterRole |
| matrix.yml | Матрица текущих прав с независимыми фильтрами |

Перед независимыми сценариями восстанавливайте baseline. При prune=false baseline не удаляет добавленные опциональные grants: для полного сброса сначала выполните cleanup, затем baseline apply. Обратная замена immutable roleRef тоже требует allow_replacement=true. Сценарии password-update, identity-in-use, cleanup-identities и прежний group-membership убраны: управление паролями и идентичностями перенесено в manifests.

Native AuthorizationRule — отдельный opt-in сценарий, которому нужны поддерживаемые user-authz accessLevel и дополнительные роли Deckhouse. Он не создаёт User/Group или Kubernetes Role/ClusterRole через Ansible. Deckhouse сам создаёт производные bindings; роль не принимает их под управление. mixed_backends=true разрешает сосуществование стандартного RBAC с такими производными объектами.

## Файлы на Ansible controller

```yaml
k8s_configuration_report_path: "{{ playbook_dir }}/output/{{ inventory_hostname }}/dry.yml"
k8s_configuration_export_destination: "{{ playbook_dir }}/output/{{ inventory_hostname }}/export.yml"
k8s_configuration_export_audit_destination: "{{ playbook_dir }}/output/{{ inventory_hostname }}/export-audit.yml"
k8s_configuration_matrix_output_dir: "{{ playbook_dir }}/output/{{ inventory_hostname }}"
k8s_configuration_matrix_filename: matrix.csv
k8s_configuration_matrix_bindings_filename: bindings.csv
k8s_configuration_matrix_subjects_filename: subjects.csv
```

Пути и имена заданы в inventory. Относительные пути считаются от playbook_dir на controller. Новые каталоги 0700, файлы 0600; --check прогнозирует запись. changed в dry/export/matrix может означать сохранение файлов, без изменения Kubernetes API. Дополнительный localhost в inventory и fetch не нужны.

## Export и adoption

```bash
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e manual_dkp_mode=export
```

Export сохраняет в output/dkp/export.yml только k8s_configuration_grants, без k8s_configuration_users и k8s_configuration_groups, и отдельно пишет аудит. Зависимости локальных учёток исключены: subjects остаются точными email/claims. Файл можно подключить для применения назначений. На другом кластере предварительно подготовьте namespace и используемые Role/ClusterRole; определения пользователей и групп в экспорт не входят.

Inventory и export используют компактные subjects, roleRef и scope. Новый baseline grant cluster-node-readers создаёт ClusterRoleBinding для группы ldap:dkp-access:node-readers с ролью dkp-access-node-reader (чтение nodes). Остальные namespace-назначения используют scope.namespaces; cluster-назначение использует scope: {cluster: true}.


Для ручного изменения примените manifests/manual-binding.yml на dkp. Получите UID:

```bash
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf -n dkp-access-dev get rolebinding dkp-access-manual-reader \
  -o jsonpath='{.metadata.uid}{"\n"}'
```

Передайте его как `-e manual_dkp_adopt_uid=...` при сценарии adopt.yml. Не принимайте под управление производные user-authz bindings.

## Очистка

Сначала отзовите назначения ролью:

```bash
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/cleanup.yml -e manual_dkp_mode=apply
```

Отзываются только grants владельца manual-dkp-1734-access-test. Локальные User/Group и Role/ClusterRole сохраняются. Чужие и ручные bindings не удаляются. После native AR дождитесь удаления производных bindings контроллером Deckhouse.

Затем удалите окружение **на dkp через kubectl**:

```bash
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf delete --ignore-not-found \
  -f /tmp/k8s-access-dkp-manifests/manual-binding.yml
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf delete --ignore-not-found \
  -f /tmp/k8s-access-dkp-manifests/selector-extra.yml
sudo kubectl --kubeconfig /etc/kubernetes/admin.conf delete --ignore-not-found \
  -f /tmp/k8s-access-dkp-manifests/fixtures.yml
```

Последняя команда удаляет также тестовые локальные User/Group и дополнительные роли. LDAP-записи, стандартные роли и модули не затрагиваются.

## Матрица текущих прав

```bash
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/matrix.yml
```

Matrix можно запускать без подготовки fixtures: он читает существующий кластер. В текущем сценарии сохранено исключение system:* и d8-monitoring:scraper. Для тестовых namespace задайте `manual_dkp_matrix_namespaces: [dkp-access-dev, dkp-access-stage]` после создания окружения.

Локальные User/Group читаются из Kubernetes при каждом запуске. Роль вычисляет членство, включая вложенные локальные группы и устаревшее User.spec.groups, и считает его полным для локальной аутентификации. Для локальных пользователей выводятся буквы и точки. Изменения состава Group через kubectl учитываются следующим запуском; справочника членства в inventory нет. При `resolve_group_membership: false` полнота не подтверждается, поэтому у локальных пользователей возможны `?`.

По умолчанию `k8s_configuration_matrix_include_external_users: false`: LDAP и другие внешние идентичности показываются только группами, найденными в bindings/AR/CAR. Их участники не перечисляются и не угадываются. Персональные назначения внешним User не входят в такой отчёт и не создают строки. Это фильтр аудита: apply продолжает назначать права и вымышленным LDAP User из baseline.

Для явного просмотра прямых назначений внешним пользователям можно включить `k8s_configuration_matrix_include_external_users: true`; показываются только прямые права заглавными буквами и точками. Маска GLWCUPDX и специальные verbs Y/y сохраняются.

### Как указать пользователя Active Directory / LDAP

В `subjects` задайте `kind: User`, а в `name` — точное имя, которое Kubernetes получает после аутентификации пользователя через AD/LDAP. Регистр и префиксы сохраняются. Формат зависит от настроек LDAP/Dex/OIDC: нельзя автоматически считать именем email, `DOMAIN\login` или `sAMAccountName`.

Проверьте имя с kubeconfig самого пользователя, вошедшего через AD/LDAP:

```bash
kubectl auth whoami -o yaml
```

Используйте значение `status.userInfo.username`. С административным kubeconfig команда покажет администратора, а не нужного пользователя AD.

Например, для полученного имени `ivan.petrov@example.org`:

```yaml
k8s_configuration_grants:
  - id: ad-ivan-read
    backend: rbac
    subjects:
      - kind: User
        name: 'ivan.petrov@example.org'
    roleRef:
      kind: ClusterRole
      name: view
    scope:
      namespaces: [dkp-access-dev]
```

Роль передаёт имя буквально и создаёт только назначение доступа. Создавать локальный Deckhouse User для такого назначения не требуется; вход пользователя обеспечивает настроенный внешний провайдер.

Источники: [kubectl auth whoami](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_auth/kubectl_auth_whoami/), [аутентификация Kubernetes](https://kubernetes.io/docs/reference/access-authn-authz/authentication/).

### Как LDAP-группы получают права

В Kubernetes не требуется создавать User или Group для каждой LDAP-записи. В RoleBinding/ClusterRoleBinding указывается строковое имя группы. Пользователь получает права, если аутентификация передала это же имя в groups запроса. Сравнивается точное итоговое имя, включая префиксы и регистр; исходное LDAP CN может отличаться из-за настроек LDAP/Dex/OIDC.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: example-ldap-readers
  namespace: dkp-access-dev
subjects:
- kind: Group
  apiGroup: rbac.authorization.k8s.io
  name: ldap:dkp-access:readers
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: view
```

Если токен пользователя содержит groups=["ldap:dkp-access:readers"], этот binding предоставляет view в dkp-access-dev. Объект Deckhouse Group с таким именем не требуется. Если он существует, его spec.name и совпадающий LDAP group claim относятся к одному имени группы для RBAC; metadata.name объекта само по себе не используется как claim. Отдельная локальная Group не синхронизирует пользователей LDAP. Совпадающие имена групп разных провайдеров не изолируются Kubernetes по источнику.

Источники: [группы и аутентификация Kubernetes](https://kubernetes.io/docs/reference/access-authn-authz/authentication/), [локальные Group и имена внешних групп Deckhouse](https://deckhouse.io/modules/user-authn/usage.html).

## Проверки и ограничения

Автоматические проверки шаблонизируют все inventory/scenarios без password lookup, проверяют планы baseline/native AR и неизменность User/Group/Role/ClusterRole при apply, повторном apply, смене группы в binding и cleanup. Проверка через настоящий Ansible/kubectl использует локальный HTTPS fixture; она не заменяет проверку реального Deckhouse/Dex/LDAP.

Результаты конкретного прогона фиксируются в roles/k8s-configuration/VALIDATION.md. Этот набор не применялся агентом к dkp.

## Фильтрация matrix

По умолчанию исключаются системные namespace, пользователи/группы `system:*` и столбцы ServiceAccount; строки только с точками удаляются. В Deckhouse к системным namespace относятся также `d8-*`. Скрытые группы продолжают участвовать в расчёте прав локальных Deckhouse пользователей и ServiceAccount. Строки с `?` сохраняются.

Настройки находятся в `inventory/group_vars/access_test_dkp/k8s-config.yml`; include/exclude принимают имена и glob (`*`, `?`, `[abc]`). Все фильтры пересекаются, исключение имеет приоритет. `matrix_namespaces` задаёт точные имена и не отменяет системную классификацию.

Для просмотра обычных пользователей/групп в системных namespace добавьте к обычному запуску matrix:

```bash
-e k8s_configuration_matrix_namespace_mode=system -e '{"k8s_configuration_matrix_namespaces": [], "k8s_configuration_matrix_include_cluster_scoped": false}'
```

Для просмотра во всех namespace: `-e k8s_configuration_matrix_namespace_mode=all -e '{"k8s_configuration_matrix_namespaces": []}'`. Для возврата системных столбцов и ServiceAccount дополнительно передайте:

```bash
-e '{"k8s_configuration_matrix_include_system_subjects": true, "k8s_configuration_matrix_subjects_service_accounts": true}'
```

Пример фильтров inventory:

```yaml
k8s_configuration_matrix_namespace_mode: application
k8s_configuration_matrix_namespace_include: ['access-*', 'dkp-access-*']
k8s_configuration_matrix_namespace_exclude: ['*-archive']
k8s_configuration_matrix_users_include: ['*@example.org', 'access-test:*']
k8s_configuration_matrix_users_exclude: ['bot-*']
k8s_configuration_matrix_groups_include: []
k8s_configuration_matrix_groups_exclude: []
k8s_configuration_matrix_omit_empty_rows: true
```

Пустой include не ограничивает выборку. Фильтр namespace ресурса не ограничивает namespace ServiceAccount; для этого предусмотрены отдельные `k8s_configuration_matrix_service_account_namespaces_include/exclude`. Сводка запуска показывает применённые фильтры и число исключённых namespace, субъектов и пустых строк.

### Широкие назначения

По умолчанию `k8s_configuration_matrix_exclude_broad_subjects: true` скрывает субъектов с `apiGroups: ["*"]`, `resources: ["*"]` без ограничения имён объектов — и администраторов, и имеющих только чтение. Их известные участники, включая вложенные группы, также скрываются. Учитываются и назначения на один выбранный namespace. Правила этих субъектов не создают строки отчёта. Количество и имена видны в сводке `excluded_broad_subjects` / `excluded_broad_subject_names`.

Для возврата этих субъектов и их строк добавьте к запуску matrix:

```bash
-e '{"k8s_configuration_matrix_exclude_broad_subjects": false}'
```

Остальные фильтры действуют независимо. Неизвестное внешнее членство не определяется автоматически.

Boolean-переключатели matrix принимают значения YAML и CLI key=value: например, `-e k8s_configuration_matrix_include_external_users=true`. Роль преобразует строковое значение в boolean перед проверкой схемы. Альтернативный формат extra-vars с типизированным JSON: `-e '{"k8s_configuration_matrix_include_external_users": true}'`.

Для внешних User при включённом `include_external_users` рассчитываются только прямые назначения: заглавные буквы и точки, без наследования и `?`. Точка означает отсутствие прямого назначения, а не отсутствие доступа через группы. Локальность определяется совпадением имени субъекта с нормализованным `spec.email` прочитанного Deckhouse User. В vanilla все User внешние. В `subjects.csv` поле `rights_basis` равно `direct_only` для внешних User и `direct_and_groups` для остальных субъектов. `membership_complete` по-прежнему описывает полноту сведений о группах, а не режим расчёта. Даже явно переданные memberships не включают наследование для внешнего User. В bindings.csv для такого User сохраняются только его прямые источники; широкие группы не исключают его столбец через наследование.

Файл dry содержит разделы add/change/remove и metadata (cluster_uid, cluster_version, owner, digest). Добавления и удаления описаны однократно без apiVersion/apiGroup и служебных metadata; в change.fields показаны только изменённые значения before/after. Замена отмечается replacement: true. adoption выводится только при принятии существующего объекта под управление; allow_collision — только при изменении аннотации Deckhouse. privilege_change удалён: отчёт не оценивает фактическое увеличение или уменьшение прав. После apply без изменений списки add/change/remove пусты. Для анализа разрешений используйте matrix. Диагностический результат модуля и обычный --diff сохраняют before/after; файл dry является их кратким представлением.

Проверки access_checks удалены из роли: apply и prune не выполняют SubjectAccessReview. Для просмотра фактических прав с учётом содержимого ролей используйте matrix. Дополнительные проверки bindings после apply не добавлялись.

### Матрица назначений из inventory

Для просмотра прав описанных назначений до apply:

```bash
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp -e @manual-test-dkp/scenarios/matrix-inventory.yml
```

На контроллере появятся output/dkp/{matrix,bindings,subjects}-inventory.csv. Можно также передать -e k8s_configuration_matrix_source=inventory с обычным matrix.yml. Назначения берутся только из текущего k8s_configuration_grants; роли и локальное членство — из кластера. Посторонние bindings не учитываются, state: absent пропускается. Это не полная матрица эффективного доступа после apply и не проверка возможности применения. Исходные matrix.csv/bindings.csv/subjects.csv сохраняются отдельно. Backend deckhouse (AR/CAR) в таком прогнозе не поддерживается; baseline использует rbac и работает на обеих платформах.
