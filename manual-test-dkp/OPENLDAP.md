# Dex и OpenLDAP на redos8

Инструкция для Deckhouse CE/OSS 1.73.4 и существующего LDAP `dc=example,dc=org`. Настройка Dex выполняется отдельно от роли. Роль назначает права и не изменяет LDAP, DexProvider, пользователей, пароли или состав групп.

## 1. Исходные данные и результат

| Параметр | Значение |
| --- | --- |
| LDAP | `redos8:389`, обычный LDAP без TLS |
| Bind DN | `cn=vault,ou=service,dc=example,dc=org` |
| Пользователи | `ou=people,dc=example,dc=org`, `inetOrgPerson`, логин `uid` |
| Группы | `ou=groups,dc=example,dc=org`, `groupOfNames`, имя `cn` |
| Членство | полный DN пользователя в атрибуте `member` группы |
| `developers` | alice, carol |
| `operators` | bob, carol |
| Без групп | dave |

StartTLS уже проверен и возвращает `unsupported extended operation`. Поэтому пример использует `insecureNoSSL: true`, `startTLS: false`. Пароли между Dex и LDAP передаются без шифрования; этот вариант предназначен для изолированной тестовой сети. HTTPS браузера к Dex не шифрует участок Dex → LDAP.

`mail` отсутствует: `emailAttr: uid` отображает uid в email claim Dex. Это поддерживается схемой DexProvider. Не меняйте LDAP-записи ради этого теста. Итоговые username/groups всё равно проверяются после входа.

Дополнительный сценарий [scenarios/openldap.yml](scenarios/openldap.yml) сохраняет baseline и добавляет:

| Субъект | Права |
| --- | --- |
| Group `developers` | ClusterRole `view` в `dkp-access-dev` |
| User `alice` | Role `dkp-access-named-config`: только `get` ConfigMap `public-config` в `dkp-access-stage` |

Таким образом, Alice проверяет и групповые, и персональные права, Carol — только групповые. Bob и Dave не получают прав от этих двух назначений. Другие bindings кластера могут давать им дополнительные права.

## 2. Проверить модули и сеть

На `dkp` под администратором:

```bash
export KUBECONFIG=/etc/kubernetes/admin.conf
kubectl get modules user-authn user-authz
kubectl get moduleconfigs user-authn user-authz
kubectl get crd dexproviders.deckhouse.io
kubectl -n d8-user-authn get deployment dex
kubectl -n d8-user-authn get pods -o wide
kubectl -n d8-user-authn get ingress
```

Оба модуля должны быть готовы. Если существующие ModuleConfig отключены, включите их, сохраняя текущие настройки:

```bash
kubectl patch moduleconfig user-authn --type=merge -p '{"spec":{"enabled":true}}'
kubectl patch moduleconfig user-authz --type=merge -p '{"spec":{"enabled":true}}'
kubectl get modules user-authn user-authz
```

Не заменяйте ModuleConfig целиком примером другого кластера. Для отсутствующего ModuleConfig используйте конфигурацию модуля вашей версии Deckhouse. Продолжайте после готовности обоих модулей, а не сразу после успешного patch.

Проверки LDAP с узла `dkp` (пароль запрашивается интерактивно):

```bash
ldapsearch -x -H ldap://redos8:389 \
  -D 'cn=vault,ou=service,dc=example,dc=org' -W \
  -b 'ou=people,dc=example,dc=org' \
  '(&(objectClass=inetOrgPerson)(uid=alice))' uid cn
ldapsearch -x -H ldap://redos8:389 \
  -D 'cn=vault,ou=service,dc=example,dc=org' -W \
  -b 'ou=groups,dc=example,dc=org' \
  '(&(objectClass=groupOfNames)(member=uid=alice,ou=people,dc=example,dc=org))' cn member
```

Ожидается Alice и группа developers. Для проверки пользовательского пароля:

```bash
ldapwhoami -x -H ldap://redos8:389 \
  -D 'uid=alice,ou=people,dc=example,dc=org' -W
```

Доступ с узла не гарантирует доступ из pod Dex. Если утилиты есть в контейнере, проверьте:

```bash
kubectl -n d8-user-authn exec deployment/dex -- getent hosts redos8
```

Отсутствие `getent` в образе не доказывает ошибку DNS. Если имя есть только в `/etc/hosts` узла, укажите в `ldap.host` доступный из pod IP сервера redos8 с портом 389 либо настройте DNS. Проверьте маршрут и firewall: TCP/389 должен пропускать фактический исходящий адрес Dex (pod или узла при SNAT).

## 3. Создать DexProvider

Шаблон: [manifests/openldap-dex-provider.yml.example](manifests/openldap-dex-provider.yml.example). Он не содержит действующего пароля и не применяется автоматически ролью.

Из корня проекта на Ansible controller скопируйте только шаблон:

```bash
scp manual-test-dkp/manifests/openldap-dex-provider.yml.example root@dkp:/root/openldap-dex-provider.yml.example
```

На `dkp` создайте приватную рабочую копию:

```bash
umask 077
mkdir -p /root/private-openldap
cp /root/openldap-dex-provider.yml.example /root/private-openldap/provider.yml
chmod 600 /root/private-openldap/provider.yml
vi /root/private-openldap/provider.yml
```

В редакторе замените `REPLACE_WITH_VAULT_LDAP_BIND_PASSWORD` на пароль **cn=vault**, а не Alice и не значение `userPassword::` из ldapsearch. Пароль — YAML-строка; для специальных символов используйте корректное YAML-кавычкование. При необходимости замените `host` на IP redos8. Рабочий файл с паролем хранится вне репозитория; пароль можно получить из вашего Vault, но в DexProvider требуется готовое значение.

Учётка cn=vault уже имеет read для people/groups по вашим ACL. Отдельная bind-учётка необязательна для теста; при её создании нужны аналогичные ACL. Пароли пользователей и их LDAP-хеши в манифест не переносятся.

Проверьте схему и примените на `dkp`:

```bash
kubectl apply --server-side --dry-run=server --field-manager=manual-openldap \
  -f /root/private-openldap/provider.yml
kubectl apply --server-side --field-manager=manual-openldap \
  -f /root/private-openldap/provider.yml
kubectl get dexprovider openldap-redos8
kubectl -n d8-user-authn rollout status deployment/dex --timeout=180s
```

Server-side apply не создаёт аннотацию last-applied с дополнительной копией пароля. Сам `spec.ldap.bindPW` остаётся секретным значением в API: не публикуйте полный YAML DexProvider и не сохраняйте его в Git. Не используйте `--force-conflicts` при конфликте владельцев полей: сначала проверьте существующий ресурс.

Deckhouse сам формирует конфигурацию Dex из DexProvider. Не редактируйте сгенерированный ConfigMap или Deployment Dex. Успешный apply/rollout ещё не подтверждает вход в LDAP: он проверяется далее.

## 4. Войти и получить пользовательский kubeconfig

Посмотрите реальные адреса интерфейсов, не угадывая домен:

```bash
kubectl -n d8-user-authn get ingress
kubectl get moduleconfig user-authn -o yaml
```

Нужны доступные с рабочего компьютера HTTPS-адреса Dex и генератора kubeconfig, корректный DNS и доверие к CA их сертификатов. В интерфейсе входа выберите **OpenLDAP redos8**. Логин — `alice`, пароль — её действующий LDAP-пароль. Пароль cn=vault используется только внутри коннектора.

Откройте адрес генератора kubeconfig из Ingress (обычно домен с `kubeconfig`), войдите через OpenLDAP и выполните показанные генератором команды. Сохраните конфигурацию в отдельный файл, например `~/.kube/openldap-alice.yaml`, не перезаписывая административный kubeconfig. Если генератор предлагает установку exec-плагина, выполните его инструкции на компьютере с kubectl.

Если генератор/API ещё не опубликован, настройте `user-authn` через `kubectl edit moduleconfig user-authn`: в существующем `spec.settings` задайте `publishAPI.enabled: true`, сохраняя прочие настройки и текущую версию схемы ModuleConfig. Это публикует API через ingress; выберите допустимую область сетевого доступа. При необходимости добавьте в `kubeconfigGenerator` доступный пользователю `masterURI` и CA по схеме вашей версии. Затем снова проверьте Ingress и готовность модуля. Для уже настроенного прямого доступа к API публикация через ingress не требуется.

Не используйте здесь LDAP-пароль с прямым API `:6443`: данный пример использует браузерный OIDC-вход и не включает Basic Auth.

С пользовательским kubeconfig:

```bash
kubectl --kubeconfig "$HOME/.kube/openldap-alice.yaml" auth whoami -o yaml
```

Для сценария ожидаются username `alice` и группа `developers`. Если API возвращает другие строки/префиксы, используйте их буквально в параметрах сценария. Имя из kubeconfig администратора не подходит. После изменения LDAP-групп войдите заново, чтобы получить актуальный токен. Адрес Dex должен быть доступен также при обновлении токена.

Аналогично получите отдельные kubeconfig для Carol, Bob и Dave. Для LDAP-входа не создавайте локальные Deckhouse User/Group.

## 5. Подготовить ресурсы и назначить права

Сначала выполните раздел «Подготовка окружения» в [README.md](README.md#подготовка-окружения): fixtures создают namespaces и Role `dkp-access-named-config`. Это также создаёт описанные там локальные тестовые User/Group; их имена отличаются от внешних LDAP-субъектов. Если окружение уже подготовлено, повторять создание identities ради LDAP не требуется.

Из корня проекта на Ansible controller:

```bash
# План: baseline + два реальных LDAP-назначения.
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/openldap.yml
# Применение.
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/openldap.yml -e manual_dkp_mode=apply
# Повтор должен быть без изменений.
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/openldap.yml -e manual_dkp_mode=apply
```

Если whoami вернул другие claims, добавляйте к каждому запуску, например:

```bash
-e manual_dkp_openldap_user='ldap:alice' -e manual_dkp_openldap_group='ldap:developers'
```

Это пример переопределения, а не требуемый префикс: значения берите из whoami. Сценарий не включает prune, сохраняет baseline и не удаляет ранее созданные назначения. Существующие посторонние назначения могут влиять на проверку эффективных прав.

## 6. Проверить фактический доступ

На компьютере с пользовательскими kubeconfig:

```bash
# Alice: групповое чтение в dev и персональное чтение одного ConfigMap в stage.
kubectl --kubeconfig "$HOME/.kube/openldap-alice.yaml" auth can-i list pods -n dkp-access-dev
kubectl --kubeconfig "$HOME/.kube/openldap-alice.yaml" auth can-i get configmap/public-config -n dkp-access-stage
kubectl --kubeconfig "$HOME/.kube/openldap-alice.yaml" get configmap public-config -n dkp-access-stage
# Ожидается no при отсутствии других разрешающих назначений.
kubectl --kubeconfig "$HOME/.kube/openldap-alice.yaml" auth can-i create deployments -n dkp-access-dev
kubectl --kubeconfig "$HOME/.kube/openldap-alice.yaml" auth can-i list configmaps -n dkp-access-stage
# Carol: developers даёт view в dev, персональных прав Alice в stage нет.
kubectl --kubeconfig "$HOME/.kube/openldap-carol.yaml" auth can-i list pods -n dkp-access-dev
kubectl --kubeconfig "$HOME/.kube/openldap-carol.yaml" auth can-i get configmap/public-config -n dkp-access-stage
```

Ожидаемые ответы: Alice — yes/yes/успешный get/no/no, Carol — yes/no. Bob и Dave не должны получать эти разрешения от данного сценария. Роль не отзывает посторонние назначения; Kubernetes суммирует разрешения. Сама возможность войти не означает наличие доступа ко всем приложениям Deckhouse — у приложений могут быть собственные ограничения по группам.

Матрица через роль, на Ansible controller:

```bash
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/openldap.yml -e manual_dkp_mode=matrix
```

CSV сохраняются в `manual-test-dkp/output/dkp/`. `include_external_users` включён сценарием: Alice видна по прямому назначению. Матрица показывает прямое право Alice в stage и права Group developers в dev, но не вычисляет членство внешних LDAP-пользователей. Для проверки наследования используйте реальный вход и can-i, а не отсутствие букв в столбце Alice.

## 7. Отозвать только добавленные LDAP-права

Из корня проекта:

```bash
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/openldap-absent.yml
ansible-playbook -i manual-test-dkp/inventory/hosts.ini manual-test-dkp/playbook.yaml -l dkp \
  -e @manual-test-dkp/scenarios/openldap-absent.yml -e manual_dkp_mode=apply
```

Это explicit absent для двух LDAP-grants; baseline сохраняется, prune не нужен. Полный `cleanup.yml` удаляет все собственные назначения стенда и для точечного отзыва не требуется.

Для удаления самого LDAP-коннектора отдельно на `dkp`:

```bash
kubectl delete dexprovider openldap-redos8
rm -f /root/private-openldap/provider.yml
```

Удаление провайдера не удаляет bindings и не гарантирует немедленного отзыва уже выданных токенов. Сначала отзовите права. LDAP-записи и bind-учётка Vault сохраняются.

## Диагностика

| Симптом | Что проверить |
| --- | --- |
| `unsupported extended operation` | Не включён ли startTLS; этот сервер работает без него |
| `no such host` | DNS внутри Dex pod; имя из hosts узла не передаётся в pod автоматически |
| timeout / connection refused | IP, порт 389, firewall, маршрутизация из pod |
| Invalid credentials | Правильный пароль cn=vault и отдельно правильный пароль пользователя |
| Пользователь не найден | baseDN people, inetOrgPerson, uid, read ACL bind-учётки |
| Нет developers в whoami | groupOfNames, DN → member, nameAttr cn; новый вход после изменения групп |
| Вход успешен, но Forbidden | Фактические username/groups, namespace, roleRef и применённые bindings |
| Alice не наследует группу в CSV | Для внешних User матрица учитывает только прямые назначения |

При необходимости смотрите `kubectl -n d8-user-authn logs deployment/dex --since=10m`. Не публикуйте токены, пароли и полные конфигурации из логов/ресурсов.

Источники: [схема DexProvider именно v1.73.4](https://github.com/deckhouse/deckhouse/blob/v1.73.4/modules/150-user-authn/crds/dex-provider.yaml), [LDAP в Deckhouse](https://deckhouse.io/modules/user-authn/usage.html#ldap), [получение kubeconfig](https://deckhouse.io/products/kubernetes-platform/documentation/v1/admin/configuration/access/authentication/k8s-api-lb.html), [LDAP-коннектор Dex](https://dexidp.io/docs/connectors/ldap/). Новые возможности актуальной документации могут отсутствовать в 1.73.4; в этой инструкции не используются DexProviderCheck, Kerberos или отдельная установка Dex.
