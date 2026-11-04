import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "filter_plugins"))
from k8s_configuration_yaml import compact_yaml


class CompactYAMLTests(unittest.TestCase):
    def test_compact_fields_and_lossless_inventory_round_trip(self):
        data = {"k8s_configuration_grants": [{
            "id": "пример", "backend": "rbac",
            "subjects": [{"kind": "Group", "name": "ldap:team, #1"}],
            "roleRef": {"kind": "ClusterRole", "name": "view"},
            "scope": {"namespaces": ["dev", "stage"]},
        }, {
            "id": "cluster", "backend": "rbac",
            "subjects": [{"kind": "User", "name": "true"}],
            "roleRef": {"kind": "ClusterRole", "name": "node-reader"},
            "scope": {"cluster": True},
        }]}
        text = compact_yaml(data)
        self.assertEqual(yaml.safe_load(text), data)
        self.assertIn("roleRef: {kind: ClusterRole, name: view}", text)
        self.assertIn("scope: {namespaces: [dev, stage]}", text)
        self.assertIn("scope: {cluster: true}", text)
        self.assertIn("- {kind: Group, name:", text)
        self.assertEqual(compact_yaml(data), text)
