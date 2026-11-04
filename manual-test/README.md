# Ручная проверка k8s-configuration на redos8

Все команды Ansible ниже выполняются из **корня проекта**. `playbook.yaml` только вызывает роль: в нём нет tasks, vars, vars_files, подготовки окружения и скачивания результатов.

```text
manual-test/
├── playbook.yaml
├── inventory/
│   ├── hosts.ini
│   └── group_vars/
│       └── access_test/
│           └── k8s-config.yml
├── manifests/
│   ├── fixtures.yml
│   └── manual-binding.yml
├── scenarios/                 # Необязательные overrides через -e @файл
├── output/                    # Место для скачанного экспорта
└── README.md
```

Группа в hosts.ini — `access_test`, единственный узел — `redos8`. Ansible автоматически загружает `inventory/group_vars/access_test/k8s-config.yml`. В playbook указано `hosts: access_test`; узел можно дополнительно выбирать через `-l redos8`. Здесь находятся **все базовые данные**: become, соединение с API, режим, grants. Файлы scenarios не загружаются автоматически и не влияют на baseline.

Ссылка `../roles/k8s-configuration` в playbook задаётся относительно расположения playbook. Поэтому отдельный ANSIBLE_ROLES_PATH или vars в playbook не требуются.

## Подключение

В `inventory/hosts.ini` указаны hostname `redos8`, SSH-пользователь `devuser` и `/usr/bin/python3`. Исправьте их, если ваша среда отличается. `ansible_become: true` находится в group_vars; если sudo требует пароль, добавляйте `-K`. Для SSH по паролю используется `-k`.

Роль запускает kubectl по SSH **на redos8** с `/etc/rancher/k3s/k3s.yaml`. Копировать kubeconfig на управляющий компьютер или менять адрес API `127.0.0.1` не требуется. Путь меняется в `k8s-config.yml` через manual_test_kubeconfig. Control node требует Ansible с совместимым Python, redos8 — Python >=3.8 и установленный kubectl. Роль использует `/usr/local/bin/kubectl` (обычно k3s устанавливает этот symlink); путь меняется через `manual_test_kubectl`. PyYAML на redos8 не требуется. Контекст при необходимости задаётся в `k8s_configuration_config_connection_context`, иначе используется current-context.

```bash
ansible -i manual-test/inventory/hosts.ini access_test -m ansible.builtin.ping
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml --syntax-check
```

Роль проверяет итоговый набор после `hosts:` и `-l`: один узел допустим, несколько приводят к ошибке до запуска kubectl, в том числе при `serial: 1`. Группы, all, списки и шаблоны разрешены. В текущем inventory группа содержит только redos8, поэтому ограничение необязательно:

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml -l redos8
```

Для выполнения на controller добавьте localhost в inventory с `ansible_connection: local` и в группу access_test, подготовьте его kubeconfig/переменные и используйте `-l localhost`. Общие group_vars включают become и k3s-путь: при необходимости переопределите их для localhost. После добавления второго узла запуск без ограничения завершится ошибкой. API должен быть доступен с controller; export/report записываются на выбранном узле.

## Подготовка окружения через манифесты

Скопируйте каталог `manual-test/manifests` на redos8, например:

```bash
scp -r manual-test/manifests devuser@redos8:/tmp/k8s-access-manual-manifests
```

**На redos8** выполните:

```bash
sudo /usr/local/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml \
  apply -f /tmp/k8s-access-manual-manifests/fixtures.yml
```

Используйте `-f fixtures.yml`, а не весь каталог: manual-binding.yml — отдельный необязательный сценарий.

Создаются три namespace: access-test-dev, access-test-stage и access-test-outside; два ServiceAccount в dev; две ConfigMap в stage; три Role и один ClusterRole. Рабочие Pod и скачивание образов не требуются. Только стандартные Kubernetes-объекты, без ролей k3s/Istio/provisioner. Из приложенного списка используются `view`, `edit`, `admin`; недостающие роли определены в fixtures.yml:

| Роль | Область | Разрешения |
| --- | --- | --- |
| access-test-pod-logs | dev | Чтение Pod и pods/log; без exec/Secrets |
| access-test-config-reader | stage | Только get ConfigMap public-config; без list |
| access-test-deployer | dev | CRUD Deployments и чтение ConfigMap; без Secrets |
| access-test-node-reader | кластер | get/list/watch Nodes; без изменения Nodes |

## Субъекты и покрытие

В vanilla Kubernetes нет объектов обычных User/Group. Здесь это внешние имена, а не создаваемые логины. Переменные роли `k8s_configuration_users/groups` намеренно не заданы. Членство в группах моделируется явными claims в проверках; роль не создаёт членство в IdP. Проверка реального входа пользователя потребует отдельно настроенной аутентификации.

Все пользовательские имена начинаются с `access-test:`. Имена групп: `access-test:readers`, `access-test:developers`, `access-test:ops`.

| Пользователь/ServiceAccount | Группы в проверке | Назначение |
| --- | --- | --- |
| alice | readers | view в dev и stage; без Secrets, записи и outside |
| bob | developers | edit только в dev; включая Secrets в dev |
| alice | readers + developers | Проверка сложения групповых прав; запись только в dev |
| charlie | Нет | Прямой view в dev; в update заменяется на charlie-next |
| auditor | Нет | Именованная Role для Pod/логов в dev, без exec |
| config-reader | Нет | Только public-config в stage; private-config/list запрещены |
| tenant-admin | Нет | admin только в stage; без удаления Namespace и прав в dev |
| infra | Нет | ClusterRoleBinding на чтение Nodes |
| olivia | ops | Та же ClusterRoleBinding со вторым субъектом Group |
| upgrader | Нет | view в dev; replace меняет roleRef на edit |
| temporary | Нет | Временный view в dev для absent/prune |
| deploy-bot (SA в dev) | Стандартные SA-группы | Role на Deployments в dev |
| read-bot (SA в dev) | Стандартные SA-группы | RoleBinding в stage с субъектом из другого namespace |
| nobody, charlie-next; alice/olivia без групп | Нет | Отрицательные проверки изоляции |

Базовый набор: **11 grants → 11 RoleBinding + 1 ClusterRoleBinding**, **36 проверок** разрешённого/запрещённого доступа. Есть User/Group/ServiceAccount, несколько subjects в одной привязке, несколько namespace из одного grant, Role и ClusterRole в RoleBinding, ClusterRoleBinding, resourceNames, subresource и явный target_name с двоеточием.

Исполнитель использует настроенный kubeconfig для применения назначений. Фактические права по содержимому ролей можно посмотреть в matrix.

## Dry, apply, check/diff

```bash
# Самостоятельный dry по умолчанию; ожидаются 12 добавлений после подготовки.
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml

# Обычные check/diff без изменений.
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e manual_test_mode=apply --check --diff

# Применение назначений.
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e manual_test_mode=apply --diff

# Повторный apply: changed=false у задачи роли.
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml -e manual_test_mode=apply
```

Обычный prune выключен. Owner — manual-redos8-access-test. Изменение namespace-ресурсов ограничено dev/stage; outside служит отрицательным контролем. Две ConfigMap позволяют вручную выполнить настоящий GET.

## Необязательные сценарии

Сценарий выбирается явным подключением **одного** файла через `-e @manual-test/scenarios/<имя>.yml`. Дополнительных загрузчиков переменных в playbook нет.

| Файл в scenarios | Результат после baseline apply |
| --- | --- |
| update.yml | Один update: charlie → charlie-next |
| absent.yml | Удаление временного binding через state=absent, без prune |
| prune.yml | То же удаление через отсутствие в desired и prune=true |
| replace.yml | Замена roleRef view → edit; по умолчанию отказ, нужно явное разрешение |
| protected.yml | Отказ для namespace default, даже внутри management scope |
| empty-guard.yml | Отказ от пустого desired при prune без allow_empty_desired |
| deletion-limit.yml | Отказ от удаления из-за max_deletions=0 |
| adopt.yml | Принятие ручного binding только по точному UID |
| cleanup.yml | Удаление всех собственных тестовых bindings и проверка отзыва |

Пример изменения:

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/update.yml
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/update.yml -e manual_test_mode=apply --diff
```

**Между независимыми сценариями возвращайте baseline**, выполняя apply без файла scenarios. Это вернёт charlie и создаст удалённый temporary-reader. После успешного replace обратная замена edit → view тоже требует разрешения:

```bash
# Отказ без разрешения; затем явное разрешение replace.
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/replace.yml
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/replace.yml -e manual_test_allow_replacement=true -e manual_test_mode=apply --diff
# Вернуться к baseline:
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e manual_test_allow_replacement=true -e manual_test_mode=apply
```

При replace изменяется UID access-test-upgrade и возможен краткий перерыв доступа. Сценарии protected/empty-guard/deletion-limit запускайте после baseline, в dry: ожидается ошибка до записи в кластер.

## Файлы результатов на controller

Dry сохраняет `output/HOST/dry.yml`, export — `output/HOST/export.yml` и `export-audit.yml`, matrix — три CSV в том же каталоге. HOST — имя inventory-узла, а output находится рядом с playbook на Ansible controller. kubectl по-прежнему выполняется на target host. Каталоги создаются автоматически; новые каталоги 0700, файлы 0600. Дополнительный localhost в inventory и fetch не нужны.

Расположение и имена заданы в inventory/group_vars:

```yaml
k8s_configuration_report_path: "{{ playbook_dir }}/output/{{ inventory_hostname }}/dry.yml"
k8s_configuration_export_destination: "{{ playbook_dir }}/output/{{ inventory_hostname }}/export.yml"
k8s_configuration_export_audit_destination: "{{ playbook_dir }}/output/{{ inventory_hostname }}/export-audit.yml"
k8s_configuration_matrix_output_dir: "{{ playbook_dir }}/output/{{ inventory_hostname }}"
k8s_configuration_matrix_filename: matrix.csv
k8s_configuration_matrix_bindings_filename: bindings.csv
k8s_configuration_matrix_subjects_filename: subjects.csv
```

Относительные пути считаются от playbook_dir на controller. --check прогнозирует запись, не создавая файлы. changed может означать сохранение результата, хотя Kubernetes API не изменялся.

## Export и ручные изменения

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml -e manual_test_mode=export
```

Экспорт сохраняется **на Ansible controller**: `manual-test/output/redos8/export.yml` и `manual-test/output/redos8/export-audit.yml`. Первый файл содержит переменные роли без обёртки; второй — аудит. Export --check только проверяет необходимость записи файлов.

Файлы уже локальные, скачивание не требуется. Пример проверки импорта:

```bash

# Прогноз импорта baseline-снимка без изменения содержимого файла:
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/output/redos8/export.yml -e manual_test_mode=apply --check --diff
```

Для настоящего импорта снимите --check. Экспортные IDs могут один раз изменить provenance-аннотации; повторный импорт того же файла должен быть идемпотентен. На другом кластере нужны аналогичные Namespace/Role/ServiceAccount и его kubeconfig.

Пример ручной правки собственного binding **на redos8**:

```bash
sudo /usr/local/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml \
  -n access-test-dev patch rolebinding access-test:direct-reader --type=merge \
  -p '{"subjects":[{"kind":"User","name":"access-test:charlie-next","apiGroup":"rbac.authorization.k8s.io"}]}'
```

Dry baseline предложит вернуть charlie, managed export сохранит фактического charlie-next. При импорте такого снимка подключите также scenarios/update.yml, чтобы проверки соответствовали изменённым правам. Baseline apply вернёт исходные настройки.

## Ручной объект и adoption

**На redos8** отдельно создайте unowned binding:

```bash
sudo /usr/local/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml \
  apply -f /tmp/k8s-access-manual-manifests/manual-binding.yml
sudo /usr/local/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml \
  -n access-test-dev get rolebinding access-test-manual-reader -o jsonpath='{.metadata.uid}'
```

Managed export этот объект не включает. Scoped экспорт включает ручные объекты по указанным в group_vars ролям и namespace; он может выбрать и другие существующие назначения тем же ролям, поэтому проверьте аудит:

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e manual_test_mode=export -e manual_test_export_scope=scoped
```

Для adoption подставьте полученный UID. Сначала dry, затем apply:

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/adopt.yml -e manual_test_adopt_uid=UUID_ИЗ_API
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/adopt.yml -e manual_test_adopt_uid=UUID_ИЗ_API -e manual_test_mode=apply --diff
```

Неверный UID должен дать отказ. Export не меняет владение; imported target_name не отменяет adoption.

## Дополнительная проверка kubectl

Следующие команды выполняются **на redos8** после baseline apply:

```bash
k() { sudo /usr/local/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml "$@"; }

k auth can-i list pods -n access-test-dev --as=access-test:alice --as-group=system:authenticated --as-group=access-test:readers  # yes
k auth can-i get secrets -n access-test-dev --as=access-test:alice --as-group=system:authenticated --as-group=access-test:readers  # no
k auth can-i create deployments.apps -n access-test-dev --as=access-test:bob --as-group=system:authenticated --as-group=access-test:developers  # yes
k auth can-i list nodes --as=access-test:infra --as-group=system:authenticated  # yes
k auth can-i patch nodes --as=access-test:infra --as-group=system:authenticated  # no
k auth can-i list pods -n access-test-stage --as=system:serviceaccount:access-test-dev:read-bot  # yes
k auth can-i list pods -n access-test-dev --as=system:serviceaccount:access-test-dev:read-bot  # no

k get configmap public-config -n access-test-stage --as=access-test:config-reader --as-group=system:authenticated  # объект прочитан
k get configmap private-config -n access-test-stage --as=access-test:config-reader --as-group=system:authenticated  # Forbidden
```

Эти команды проверяют авторизацию через impersonation, а не вход с паролем. Исполнителю нужны административные полномочия impersonate.

## Очистка

Сначала отозвать собственные права (команды на управляющем компьютере):

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/cleanup.yml
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml \
  -e @manual-test/scenarios/cleanup.yml -e manual_test_mode=apply --diff
```

Затем **на redos8** удалить оснастку:

```bash
sudo /usr/local/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml \
  delete --ignore-not-found=true -f /tmp/k8s-access-manual-manifests/fixtures.yml
```

Cleanup удаляет только bindings owner manual-redos8-access-test, включая принятый через adopt объект. Unowned ручной binding остаётся до удаления тестового namespace. Удаление fixtures удалит три тестовых namespace со всем их содержимым и ClusterRole access-test-node-reader: не размещайте там другие данные. Сначала cleanup необходим также для удаления ClusterRoleBinding, который не исчезает при удалении namespace.

Локальные файлы результатов в output остаются для анализа. output/.gitignore исключает локальные результаты из случайного коммита.

## Матрица текущих прав

После применения baseline выполните из корня проекта:

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml -l redos8 \
  -e @manual-test/scenarios/matrix.yml
```

На Ansible controller появятся `manual-test/output/redos8/{matrix,bindings,subjects}.csv`. Это чтение фактических прав, включая ручные bindings; доступа к API на запись нет. Маска GLWCUPDX: get/list/watch/create/update/patch/delete/deletecollection. Заглавная буква — прямое назначение, строчная — через группу, `.` — права нет в выбранном RBAC при известном членстве, `?` — членство неполно. Специальные действия имеют отдельные строки Y/y/./?.

Сценарий не содержит справочника членства пользователей. Внешние идентичности по умолчанию показаны только группами: видны права readers/developers без восстановления их участников. Для просмотра прямых User bindings включите k8s_configuration_matrix_include_external_users; показываются только прямые права заглавными буквами и точками. Namespace ограничены тестовым набором, кластерные ресурсы включены отдельно; системные субъекты/namespace исключаются стандартными фильтрами.

`--check` строит отчёт и прогнозирует файлы без записи. Повторный запуск без изменений идемпотентен. CSV уже находятся на controller, скачивание не требуется.


В том же каталоге находятся bindings.csv (источники) и subjects.csv (известные группы). Файлы 0600, каталог 0700. Матрица не учитывает другие authorizers, admission, bypass system:masters и косвенные способы повышения прав; подробности в README роли.

## Проверки подготовки

Проверяются автоматическая загрузка inventory/group_vars, шаблоны, типы переменных, syntax-check и планы сценариев через локальный API fixture роли. Это не заменяет 36 проверок авторизации на настоящем k3s. Подключение к redos8 и применение манифестов при подготовке примера не выполняются. Файлы UTF-8/LF.

## Фильтрация matrix

По умолчанию исключаются системные namespace, пользователи/группы `system:*` и столбцы ServiceAccount; строки только с точками удаляются. В Deckhouse к системным namespace относятся также `d8-*`. Скрытые группы продолжают участвовать в расчёте прав локальных Deckhouse пользователей и ServiceAccount. Строки с `?` сохраняются.

Настройки находятся в `inventory/group_vars/access_test/k8s-config.yml`; include/exclude принимают имена и glob (`*`, `?`, `[abc]`). Все фильтры пересекаются, исключение имеет приоритет. `matrix_namespaces` задаёт точные имена и не отменяет системную классификацию.

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

## Внешние пользователи в matrix

В vanilla Kubernetes нет реестра локальных User/Group. По умолчанию matrix показывает внешние идентичности только группами: `k8s_configuration_matrix_include_external_users: false`. Членство пользователей по inventory не моделируется. Для аудита прямых User bindings включите эту переменную; показываются только прямые права заглавными буквами и точками. Применение назначений пользователям не зависит от фильтра матрицы.

Для внешних User при включённом `include_external_users` рассчитываются только прямые назначения: заглавные буквы и точки, без наследования и `?`. Точка означает отсутствие прямого назначения, а не отсутствие доступа через группы. Локальность определяется совпадением имени субъекта с нормализованным `spec.email` прочитанного Deckhouse User. В vanilla все User внешние. В `subjects.csv` поле `rights_basis` равно `direct_only` для внешних User и `direct_and_groups` для остальных субъектов. `membership_complete` по-прежнему описывает полноту сведений о группах, а не режим расчёта. Даже явно переданные memberships не включают наследование для внешнего User. В bindings.csv для такого User сохраняются только его прямые источники; широкие группы не исключают его столбец через наследование.

Файл dry содержит разделы add/change/remove и metadata (cluster_uid, cluster_version, owner, digest). Добавления и удаления описаны однократно без apiVersion/apiGroup и служебных metadata; в change.fields показаны только изменённые значения before/after. Замена отмечается replacement: true. adoption выводится только при принятии существующего объекта под управление; allow_collision — только при изменении аннотации Deckhouse. privilege_change удалён: отчёт не оценивает фактическое увеличение или уменьшение прав. После apply без изменений списки add/change/remove пусты. Для анализа разрешений используйте matrix. Диагностический результат модуля и обычный --diff сохраняют before/after; файл dry является их кратким представлением.

Проверки access_checks удалены из роли: apply и prune не выполняют SubjectAccessReview. Для просмотра фактических прав с учётом содержимого ролей используйте matrix. Дополнительные проверки bindings после apply не добавлялись.

Inventory и export записывают subjects, roleRef и scope в компактном YAML. Экспорт по умолчанию содержит только k8s_configuration_grants, без определений User/Group. Пример ClusterRoleBinding: назначение access-test-node-reader с scope: {cluster: true}.

### Матрица назначений из inventory

Для просмотра прав описанных назначений до apply:

```bash
ansible-playbook -i manual-test/inventory/hosts.ini manual-test/playbook.yaml -l redos8 -e @manual-test/scenarios/matrix-inventory.yml
```

На контроллере появятся output/redos8/{matrix,bindings,subjects}-inventory.csv. Можно также передать -e k8s_configuration_matrix_source=inventory с обычным matrix.yml. Назначения берутся только из текущего k8s_configuration_grants; роли и локальное членство — из кластера. Посторонние bindings не учитываются, state: absent пропускается. Это не полная матрица эффективного доступа после apply и не проверка возможности применения. Исходные matrix.csv/bindings.csv/subjects.csv сохраняются отдельно. Backend deckhouse (AR/CAR) в таком прогнозе не поддерживается; baseline использует rbac и работает на обеих платформах.
