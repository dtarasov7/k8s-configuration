"""Assignments may refer to identities, but cannot manage their lifecycle."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import FakeAPI, config, engine, grant, HASH
from access_manager.render import keys
from access_manager.schema import AccessError, validate_inventory
from access_manager.settings import argument_spec


class NoIdentityManagementTests(unittest.TestCase):
    def test_removed_module_parameters_are_not_accepted(self):
        spec = argument_spec()
        for name in ('users', 'groups', 'config_deckhouse_password_updates',
                     'config_management_prune_identities',
                     'config_deckhouse_api_versions_user', 'config_deckhouse_api_versions_group',
                     'config_deckhouse_ready_checks_user_authn'):
            with self.subTest(name=name):
                self.assertNotIn(name, spec)
        for name in ('users', 'groups'):
            with self.subTest(section=name), self.assertRaises(TypeError):
                validate_inventory(config(True), **{name: []})

    def test_apply_prune_and_export_preserve_preexisting_owned_identities(self):
        from access_manager.export import export_state
        api = FakeAPI()
        cfg = config(True, management={'prune': True}, safety={'allow_empty_desired': True})
        labels = keys(cfg)
        identities = {}
        for kind, spec in (('User', {'email': 'jane@example.org', 'password': HASH}),
                           ('Group', {'name': 'devs', 'members': [{'kind': 'User', 'name': 'jane'}]})):
            name = 'jane' if kind == 'User' else 'developers'
            path = '/apis/deckhouse.io/%s/%s/%s' % (
                'v1' if kind == 'User' else 'v1alpha1', 'users' if kind == 'User' else 'groups', name)
            obj = api.store({'apiVersion': 'deckhouse.io/' + ('v1' if kind == 'User' else 'v1alpha1'),
                             'kind': kind, 'metadata': {'name': name, 'labels': {
                                 labels['owner']: 'test', labels['managed-by']: 'ansible',
                                 labels['section']: 'users' if kind == 'User' else 'groups'}},
                             'spec': spec})
            identities[path] = copy.deepcopy(obj)
        assignment = grant(subjects=[{'kind': 'User', 'name': 'jane@example.org'},
                                     {'kind': 'Group', 'name': 'devs'}])
        self.assertTrue(engine(api, cfg, grants=[assignment]).apply())
        self.assertFalse(engine(api, cfg, grants=[assignment]).apply())
        self.assertTrue(engine(api, cfg, grants=[]).apply())
        export_state(engine(api, cfg), {})
        for path, obj in identities.items():
            self.assertEqual(api.objects[path], obj)
        self.assertTrue(all('/users' not in call[1] and '/groups' not in call[1]
                            for call in api.calls))

    def test_removed_internal_opt_ins_are_rejected(self):
        with self.assertRaises(AccessError):
            config(True, management={'prune_identities': True})
        cfg = config(True)
        cfg['deckhouse']['profiles']['fixture']['password_updates'] = True
        with self.assertRaises(AccessError):
            engine(cfg=cfg)
