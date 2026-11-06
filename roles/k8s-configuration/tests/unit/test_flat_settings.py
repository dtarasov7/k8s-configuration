"""Validate the public variable interface and shipped manual scenarios with Ansible."""
import os
import re
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import ROLE, render_settings

# Keep Ansible's temporary files inside the workspace.
os.environ.setdefault("ANSIBLE_LOCAL_TEMP", str(ROLE.parents[1] / ".test-tmp/flat-template"))
from access_manager.schema import validate_config
from access_manager.matrix import validate_matrix
from access_manager.export import validate_export


class FlatSettingsTests(unittest.TestCase):
    def load(self, path):
        return yaml.safe_load(path.read_text())

    def test_public_defaults_are_flat(self):
        defaults = self.load(ROLE / "defaults/main.yml")
        self.assertTrue(all(not isinstance(value, dict) for value in defaults.values()))

    def test_defaults_have_runtime_consumers(self):
        defaults = self.load(ROLE / "defaults/main.yml")
        runtime = "\n".join(
            path.read_text()
            for folder in ("tasks", "handlers", "templates", "vars", "library", "module_utils", "filter_plugins")
            for path in (ROLE / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
        for key in defaults:
            with self.subTest(variable=key):
                self.assertRegex(runtime, r"\b" + re.escape(key) + r"\b")

    def test_matrix_boolean_cli_strings_are_normalized_before_schema_validation(self):
        defaults = self.load(ROLE / "defaults/main.yml")
        flags = ("include_system_subjects", "include_external_users", "omit_empty_rows", "exclude_broad_subjects",
                 "include_cluster_scoped", "subjects_users", "subjects_groups", "subjects_service_accounts",
                 "resolve_group_membership")
        for flag in flags:
            for value, expected in (("true", True), ("false", False)):
                with self.subTest(flag=flag, value=value):
                    variables = dict(defaults)
                    variables.update(playbook_dir="/unused", inventory_hostname="dkp")
                    variables["k8s_configuration_matrix_" + flag] = value
                    matrix = validate_matrix(render_settings(variables)["matrix"])
                    actual = matrix["subjects"][flag[len("subjects_"):]] if flag.startswith("subjects_") else matrix[flag]
                    self.assertIs(actual, expected)

    def test_all_manual_settings_and_scenarios_render_and_validate(self):
        defaults = self.load(ROLE / "defaults/main.yml")
        for folder, group in (("manual-test", "access_test"), ("manual-test-dkp", "access_test_dkp"),
                              ("roles/k8s-configuration/examples/deckhouse", "access_test_dkp")):
            root = ROLE.parents[1] / folder
            common = self.load(root / ("inventory/group_vars/%s/k8s-config.yml" % group))
            for scenario in [None] + sorted((root / "scenarios").glob("*.yml")):
                with self.subTest(folder=folder, scenario=scenario):
                    variables = dict(defaults, **common)
                    if scenario:
                        variables.update(self.load(scenario))
                    known = set(defaults) | {"k8s_configuration_grants"}
                    unknown = {key for key in variables if key.startswith("k8s_configuration_")
                               and key not in known}
                    self.assertEqual(unknown, set(), "Unknown role variables in shipped inventory/scenario")
                    variables.update(omit="__OMIT__", playbook_dir=str(root),
                                     inventory_hostname="dkp" if folder.endswith("dkp") else "redos8",
                                     manual_dkp_adopt_uid="fixture-uid", manual_test_adopt_uid="fixture-uid")
                    settings = render_settings(variables)
                    validate_config(settings["config"])
                    validate_export(settings["export"])
                    validate_matrix(settings["matrix"])

    def test_module_interface_is_flat_and_legacy_payloads_are_absent(self):
        from access_manager.settings import argument_spec
        spec = argument_spec()
        self.assertTrue({"config_mode", "config_management_owner", "matrix_source"} <= set(spec))
        self.assertFalse({"config", "export", "matrix", "config_deckhouse_expected_image", "users", "groups",
                          "config_deckhouse_password_updates", "config_management_prune_identities",
                          "config_deckhouse_api_versions_user", "config_deckhouse_api_versions_group",
                          "config_deckhouse_ready_checks_user_authn"} & set(spec))
        self.assertFalse((ROLE / "vars/main.yml").exists())
        self.assertTrue(spec["config_connection_key_content"]["no_log"])
        self.assertTrue(spec["certificates"]["options"]["content"]["no_log"])

    def test_settings_preserve_omission_and_certificate_precedence(self):
        from access_manager.settings import build_settings
        settings = build_settings({
            "config_management_namespaces": None,
            "config_connection_context": "",
            "config_expected_plan_digest": "",
            "config_deckhouse_api_versions_authorization_rule": "",
            "config_connection_ca_content": "original",
            "certificates": [{"name": "ca_content", "content": "override"}],
        })
        self.assertNotIn("namespaces", settings["config"].get("management", {}))
        self.assertNotIn("context", settings["config"]["connection"])
        self.assertNotIn("expected_plan_digest", settings["config"])
        self.assertNotIn("deckhouse", settings["config"])
        self.assertEqual(settings["config"]["connection"]["ca_content"], "override")
        settings = build_settings({"config_management_namespaces": []})
        self.assertEqual(settings["config"]["management"]["namespaces"], [])
