"""EN: Format compact inventory YAML and concise dry reports.
RU: Форматировать компактный YAML inventory и краткие отчёты dry.
"""
import json

import yaml


def dry_report(plan):
    """EN: Project a sanitized internal plan into add/change/remove sections.
    RU: Преобразовать внутренний план без секретов в разделы add/change/remove.

    Args:
        plan (dict): Engine.report output; already redacted / Результат Engine.report с удалёнными секретами.

    Returns:
        dict: Operations, changed fields, metadata and optional warnings / Операции, изменённые поля, metadata и необязательные предупреждения.
    """
    def content(obj):
        """EN: Select display fields from an already sanitized object.
        RU: Выбрать отображаемые поля уже очищенного объекта.

        Args:
            obj (dict | None): Redacted before/after object / Объект before/after без секретов.

        Returns:
            dict: Comparable display fields without API identity metadata / Сравнимые поля без служебных идентификаторов API.
        """
        if not obj:
            return {}
        result = {}
        if "roleRef" in obj:
            result["roleRef"] = {key: obj["roleRef"][key] for key in ("kind", "name")}
        if "subjects" in obj:
            result["subjects"] = sorted(
                [{key: value for key, value in subject.items() if key != "apiGroup"}
                 for subject in obj["subjects"]], key=lambda item: json.dumps(item, sort_keys=True)
            )
        if "spec" in obj:
            result["spec"] = content({"subjects": obj["spec"]["subjects"]}) if "subjects" in obj["spec"] else {}
            result["spec"].update({key: value for key, value in obj["spec"].items() if key != "subjects"})
            if "members" in result["spec"]:
                result["spec"]["members"] = sorted(result["spec"]["members"],
                                                    key=lambda item: json.dumps(item, sort_keys=True))
        return result

    def differences(before, after):
        """EN: Compare display fields recursively, ignoring implicit false CRD defaults.
        RU: Рекурсивно сравнить поля, игнорируя неявные CRD-значения false.

        Args:
            before (dict): Old display fields / Прежние отображаемые поля.
            after (dict): New display fields / Новые отображаемые поля.

        Returns:
            dict: Changed fields with before/after leaves / Изменённые поля с конечными значениями before/after.
        """
        fields = {}
        for key in sorted(set(before) | set(after)):
            old, new = before.get(key), after.get(key)
            # EN: Missing false-defaulted CRD options do not represent permission changes.
            # RU: Отсутствующая CRD-опция со значением по умолчанию false не означает изменение прав.
            if key in ("portForwarding", "allowScale") and old is None and new is False:
                continue
            if old == new:
                continue
            fields[key] = (differences(old, new) if isinstance(old, dict) and isinstance(new, dict)
                           else {"before": old, "after": new})
        return fields

    result = {"add": [], "change": [], "remove": []}
    for change in plan.get("changes", []):
        action = change["action"]
        if action == "noop":
            continue
        entry = {"kind": change["kind"], "name": change["name"]}
        if change.get("namespace"):
            entry["namespace"] = change["namespace"]
        if action in ("create", "delete"):
            entry.update(content(change["after"] if action == "create" else change["before"]))
        else:
            fields = differences(content(change["before"]), content(change["after"]))
            if fields:
                entry["fields"] = fields
            if action == "replace":
                entry["replacement"] = True
        for key in ("adoption",):
            if change.get(key):
                entry[key] = True
        result["add" if action == "create" else "remove" if action == "delete" else "change"].append(entry)
    result["metadata"] = {key: plan[key] for key in ("cluster_uid", "cluster_version", "owner", "digest")
                          if plan.get(key) is not None}
    if plan.get("warnings"):
        result["warnings"] = plan["warnings"]
    return result


class FlowMapping(dict):
    """EN: Mark a dictionary for inline YAML serialization.
    RU: Пометить словарь для однострочной сериализации YAML.
    """
    pass


class InventoryDumper(yaml.SafeDumper):
    """EN: Use SafeDumper with inline mappings for selected inventory fields.
    RU: Использовать SafeDumper с однострочными словарями выбранных полей inventory.
    """
    pass


InventoryDumper.add_representer(
    FlowMapping,
    lambda dumper, value: dumper.represent_mapping(
        "tag:yaml.org,2002:map", value.items(), flow_style=True
    ),
)


def compact_yaml(value):
    """EN: Serialize YAML with inline subjects, roleRef and scope mappings.
    RU: Сериализовать YAML с однострочными словарями subjects, roleRef и scope.

    Args:
        value (dict): Inventory or report with standard scalar values / Inventory или отчёт со стандартными скалярными значениями.

    Returns:
        str: UTF-8-compatible YAML ending with a newline / YAML, совместимый с UTF-8, с завершающим переводом строки.

    Raises:
        yaml.YAMLError: A value cannot be safely serialized / Значение нельзя безопасно сериализовать.
    """
    def prepare(item, flow=False):
        """EN: Copy values into plain YAML types and mark compact mappings.
        RU: Скопировать значения в обычные YAML-типы и пометить компактные словари.

        Args:
            item (Any): Serializable subtree / Сериализуемое поддерево.
            flow (bool): Render this mapping inline / Записать этот словарь в одну строку.

        Returns:
            Any: Copied subtree, preserving scalar values / Копия поддерева с сохранением скалярных значений.
        """
        if isinstance(item, dict):
            result = FlowMapping() if flow else {}
            for key, child in item.items():
                key = str(key)
                if key == "subjects" and isinstance(child, list):
                    result[key] = [prepare(subject, flow=True) for subject in child]
                else:
                    result[key] = prepare(child, flow=key in ("roleRef", "scope"))
            return result
        if isinstance(item, list):
            return [prepare(child) for child in item]
        # EN: SafeDumper needs plain strings instead of Ansible string subclasses.
        # RU: SafeDumper нужны обычные строки вместо строковых подклассов Ansible.
        return str(item) if isinstance(item, str) else item

    return yaml.dump(prepare(value), Dumper=InventoryDumper, allow_unicode=True,
                     sort_keys=False, default_flow_style=False, width=1000)


class FilterModule:
    """EN: Expose the role formatting helpers as Ansible filters.
    RU: Предоставить средства форматирования роли как фильтры Ansible.
    """
    def filters(self):
        """EN: Register the inventory YAML and dry-report filters.
        RU: Зарегистрировать фильтры YAML inventory и отчёта dry.

        Returns:
            dict[str, callable]: Filter names mapped to implementations / Соответствие имён фильтров их реализациям.
        """
        return {"k8s_configuration_compact_yaml": compact_yaml,
                "k8s_configuration_dry_report": dry_report}
