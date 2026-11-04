"""The Deckhouse manual fixture owns identities/roles; Ansible owns only grants."""
import copy
import csv
import io
import os
import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import ROLE, INFO, FakeAPI, engine, render_settings
from access_manager.schema import validate_config, validate_inventory
from access_manager.matrix import Matrix

os.environ.setdefault('ANSIBLE_LOCAL_TEMP', str(ROLE.parents[1] / '.test-tmp/manual-template'))
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

ROOT = ROLE.parents[1] / 'manual-test-dkp'


class ManualDKPTests(unittest.TestCase):
    def settings(self, scenario=None):
        def load(path):
            return yaml.safe_load(path.read_text())
        variables = dict(load(ROLE / 'defaults/main.yml'),
                         **load(ROOT / 'inventory/group_vars/access_test_dkp/k8s-config.yml'))
        if scenario:
            variables.update(load(ROOT / 'scenarios' / scenario))
        variables.update(omit='__OMIT__', playbook_dir=str(ROOT), inventory_hostname='dkp',
                         manual_dkp_adopt_uid='fixture-uid')
        templar = Templar(loader=DataLoader(), variables=variables)
        cfg = validate_config(render_settings(variables)['config'])
        values = [templar.template(variables['k8s_configuration_' + field])
                  for field in ('grants',)]
        values = [None if value == '__OMIT__' else value for value in values]
        return cfg, validate_inventory(cfg, grants=values[0])

    def fixture(self):
        api = FakeAPI()
        for doc in yaml.safe_load_all((ROOT / 'manifests/fixtures.yml').read_text()):
            if doc['kind'] in INFO:
                api.store(doc)
        api.store({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'ClusterRole',
                   'metadata': {'name': 'admin'}, 'rules': []})
        return api

    def test_local_membership_is_read_from_cluster_and_tracks_manual_changes(self):
        api = self.fixture()
        api.store({'apiVersion': 'rbac.authorization.k8s.io/v1', 'kind': 'RoleBinding',
                   'metadata': {'name': 'fixture-read', 'namespace': 'dkp-access-dev'},
                   'roleRef': {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'dkp-access-pod-logs'},
                   'subjects': [{'kind': 'Group', 'name': 'dkp-access:readers'},
                                {'kind': 'User', 'name': 'outside@example.invalid'}]})
        cfg, _ = self.settings()
        report = Matrix(api, cfg, {'namespaces': ['dkp-access-dev']}).report()
        rows = list(csv.DictReader(io.StringIO(report['files']['matrix.csv']), delimiter=';'))
        row = next(r for r in rows if r['resource'] == 'pods')
        self.assertEqual(row['User:dkp-access-alice@example.invalid'], 'glw.....')
        self.assertEqual(row['User:dkp-access-auditor@example.invalid'], '........')
        self.assertNotIn('User:outside@example.invalid', row)
        # A manual membership change in the cluster must affect the next report.
        group = next(o for o in api.objects.values() if o.get('kind') == 'Group'
                     and o['spec']['name'] == 'dkp-access:readers')
        group['spec']['members'] = [{'kind': 'User', 'name': 'dkp-access-auditor'}]
        api.store(group)
        report = Matrix(api, cfg, {'namespaces': ['dkp-access-dev']}).report()
        row = next(r for r in csv.DictReader(io.StringIO(report['files']['matrix.csv']), delimiter=';')
                   if r['resource'] == 'pods')
        self.assertEqual(row['User:dkp-access-alice@example.invalid'], '........')
        self.assertEqual(row['User:dkp-access-auditor@example.invalid'], 'glw.....')

    def test_all_scenarios_leave_identities_outside_ansible_management(self):
        for scenario in [None] + [p.name for p in sorted((ROOT / 'scenarios').glob('*.yml'))]:
            with self.subTest(scenario=scenario):
                cfg, inventory = self.settings(scenario)
                self.assertEqual(set(inventory), {'grants'})
                for grant in inventory['grants'] or []:
                    for subject in grant.get('subjects', []):
                        self.assertNotIn('source', subject)

    def test_baseline_apply_idempotence_cleanup_preserve_users_groups_and_roles(self):
        api = self.fixture()
        protected = {path: copy.deepcopy(obj) for path, obj in api.objects.items()
                     if obj.get('kind') in ('User', 'Group', 'Role', 'ClusterRole')}
        cfg, inventory = self.settings()
        count = len(engine(api, cfg, **inventory).desired)
        for scenario, expected in ((None, count), (None, 0), ('group-binding.yml', 1), ('cleanup.yml', count)):
            cfg, inventory = self.settings(scenario)
            manager = engine(api, cfg, **inventory)
            self.assertEqual(sum(op['action'] != 'noop' for op in manager.operations), expected)
            self.assertTrue(all(obj['kind'] in ('RoleBinding', 'ClusterRoleBinding')
                                for obj in manager.desired.values()))
            manager.apply()
            self.assertEqual(protected, {path: api.objects[path] for path in protected})
        self.assertFalse(any(obj.get('kind') in ('RoleBinding', 'ClusterRoleBinding') for obj in api.objects.values()))

    def test_openldap_assignments_are_additive_idempotent_and_revocable(self):
        api = self.fixture()
        cfg, baseline = self.settings()
        engine(api, cfg, **baseline).apply()
        protected = {path: copy.deepcopy(obj) for path, obj in api.objects.items()
                     if obj.get('kind') in ('User', 'Group', 'Role', 'ClusterRole')}
        cfg, inventory = self.settings('openldap.yml')
        grants = {grant['id']: grant for grant in inventory['grants']}
        self.assertEqual(grants['openldap-developers-view']['subjects'],
                         [{'kind': 'Group', 'name': 'developers'}])
        self.assertEqual(grants['openldap-alice-config']['subjects'],
                         [{'kind': 'User', 'name': 'alice'}])
        self.assertEqual(grants['openldap-alice-config']['roleRef'],
                         {'kind': 'Role', 'name': 'dkp-access-named-config'})
        manager = engine(api, cfg, **inventory)
        self.assertEqual(manager.report()['summary']['create'], 2)
        self.assertTrue(manager.apply())
        self.assertFalse(engine(api, cfg, **inventory).apply())
        cfg, inventory = self.settings('openldap-absent.yml')
        manager = engine(api, cfg, **inventory)
        self.assertEqual(manager.report()['summary']['delete'], 2)
        self.assertTrue(manager.apply())
        self.assertFalse(engine(api, cfg, **baseline).apply())
        self.assertEqual(protected, {path: api.objects[path] for path in protected})

    def test_native_authorization_rules_reference_precreated_local_claims(self):
        cfg, inventory = self.settings('basic-namespaced.yml')
        manager = engine(self.fixture(), cfg, **inventory)
        self.assertEqual({obj['kind'] for obj in manager.desired.values()}, {'RoleBinding', 'ClusterRoleBinding', 'AuthorizationRule'})
        self.assertEqual(sum(obj['kind'] == 'AuthorizationRule' for obj in manager.desired.values()), 6)
        self.assertTrue(all(key[0] not in ('User', 'Group', 'Role', 'ClusterRole') for key in manager.desired))
