# Пример управления доступом в Deckhouse

Самостоятельный пример по структуре `manual-test-dkp`: INI-инвентарь, group_vars, манифесты окружения и отдельные сценарии. Команды ниже выполняются из корня проекта. Собственный owner — `example-dkp-1734-access-test`, файлы результатов сохраняются на controller в `examples/deckhouse/output/dkp/`.

## Инвентарь и параметры

```ini
[access_test_dkp]
dkp ansible_host=dkp ansible_user=root ansible_python_interpreter=/usr/bin/python3
```

Исправьте `inventory/hosts.ini` под свой узел. Роль и kubectl запускаются на одном выбранном узле `dkp`; `inventory/group_vars/access_test_dkp/k8s-config.yml` задаёт путь `/etc/kubernetes/admin.conf`, `become: true` и режим dry. При необходимости смените `example_dkp_kubeconfig`, `example_dkp_kubectl`, SSH-пользователя; для sudo с паролем добавьте `-K`.

Нужны Python >=3.8 и kubectl на target, Ansible на controller, готовые модули user-authn/user-authz и API/CRD Deckhouse 1.73.4. Зависимости роль не устанавливает. Playbook использует роль по относительному пути, поэтому пример работает и после копирования всего каталога роли.

## Подготовка

`manifests/fixtures.yml` создаёт тестовые namespace, Role/ClusterRole и локальные Deckhouse User/Group, но не назначения прав. Это отдельная подготовка окружения; роль управляет только bindings/AuthorizationRule. Fixtures содержат публичные тестовые учётки с паролем `12121212`; используйте отдельный тестовый кластер. Повторное применение возвращает локальные пароли и группы к исходному состоянию.

```bash
scp roles/k8s-configuration/examples/deckhouse/manifests/fixtures.yml root@dkp:/tmp/deckhouse-access-fixtures.yml
ssh root@dkp 'kubectl --kubeconfig /etc/kubernetes/admin.conf apply -f /tmp/deckhouse-access-fixtures.yml'
```

Fixtures используют те же имена тестовых объектов, что и `manual-test-dkp`. Owner назначений отличается: не запускайте оба набора на одних и тех же заданиях без понимания того, какие bindings останутся. Создание нового owner не принимает под управление старые bindings, а права разных bindings суммируются.

Пример компактного назначения из group_vars:

```yaml
- id: group-readers
  backend: rbac
  subjects:
  - {kind: Group, name: 'dkp-access:readers'}
  roleRef: {kind: ClusterRole, name: view}
  scope: {namespaces: [dkp-access-dev, dkp-access-stage]}
```

## План, применение и повтор

```bash
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp -e example_dkp_mode=apply --check --diff
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp -e example_dkp_mode=apply
```

Первый запуск сохраняет dry-план. Повторите последний запуск для проверки идемпотентности: при неизменном состоянии changed=0. Перед записью используйте план для проверки scope и subjects.

## Сценарии

| Файл scenarios | Действие |
| --- | --- |
| baseline.yml | Базовые RBAC-назначения из group_vars |
| update.yml | Изменение существующего назначения пользователя |
| group-binding.yml | Замена subject у назначения на локальную и внешнюю группы |
| matrix.yml | CSV текущих прав из кластера |
| matrix-inventory.yml | CSV по grants из inventory и актуальным ролям из API |
| export-scoped.yml | Ограничение экспорта выбранными ролями и namespace; задайте режим export |
| openldap.yml | Baseline + developers: view в dev; alice: get public-config в stage |
| openldap-absent.yml | Отзыв только двух OpenLDAP-назначений |
| cleanup.yml | Явный prune всех собственных назначений примера, включая отсутствующие в baseline |

```bash
# Изменение назначения: сначала dry, затем та же команда с -e example_dkp_mode=apply.
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp \
  -e @roles/k8s-configuration/examples/deckhouse/scenarios/group-binding.yml
# Матрица текущих прав.
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp \
  -e @roles/k8s-configuration/examples/deckhouse/scenarios/matrix.yml
# Экспорт назначений по выбранным ролям.
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp \
  -e @roles/k8s-configuration/examples/deckhouse/scenarios/export-scoped.yml -e example_dkp_mode=export
```

Базовые LDAP claims вымышлены. Для реального LDAP используйте фактические username/groups из `kubectl auth whoami -o yaml`. Сценарий openldap предполагает `developers` и `alice`; при необходимости переопределите `example_dkp_openldap_group` и `example_dkp_openldap_user`. Шаблон `manifests/openldap-dex-provider.yml.example` предназначен для отдельной настройки Dex с LDAP на redos8:389; заменяйте пароль bind-учётки только в приватной копии вне репозитория. Подключение без TLS подходит только для изолированного стенда. Внешние User в матрице имеют только прямые права: наследование LDAP-групп проверяйте реальным входом, а не CSV.

## Отзыв назначений

```bash
# План удаления только собственных назначений этого примера.
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp \
  -e @roles/k8s-configuration/examples/deckhouse/scenarios/cleanup.yml
# Применение проверенного плана.
ansible-playbook -i roles/k8s-configuration/examples/deckhouse/inventory/hosts.ini \
  roles/k8s-configuration/examples/deckhouse/playbook.yml -l dkp \
  -e @roles/k8s-configuration/examples/deckhouse/scenarios/cleanup.yml -e example_dkp_mode=apply
```

Это сценарий inventory, а не задача clean.yml и не тег clean. Он не удаляет LDAP-записи, User/Group, namespace, определения Role/ClusterRole и отчёты. Такие ресурсы при необходимости удаляются отдельно их владельцем.
