"""Require one effective play host after --limit, independently of serial batches."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROLE = Path(__file__).resolve().parents[2]


class TargetTests(unittest.TestCase):
    def run_selector(self, hosts, limit=None, serial=None, expect_ok=False, tags='pre-req', target=None,
                     include_localhost=False):
        root = ROLE.parents[1] / '.test-tmp'
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            path = Path(directory)
            inventory = path / 'hosts.ini'
            inventory.write_text(
                '[single]\nnode1 ansible_connection=local\n'
                '[multiple]\nnode1\nnode2 ansible_connection=local\n'
                + ('[controllers]\nlocalhost ansible_connection=local\n' if include_localhost else '')
            )
            play = {
                'hosts': hosts, 'gather_facts': False,
                'vars': {'k8s_configuration_config_connection_kubeconfig': '/unused'},
                'roles': ['k8s-configuration'],
            }
            if serial:
                play['serial'] = serial
            if target:
                play['vars']['target_host'] = target
            book = path / 'play.yml'
            book.write_text(yaml.safe_dump([play]))
            env = dict(os.environ, ANSIBLE_LOCAL_TEMP=str(path / 'local'),
                       ANSIBLE_REMOTE_TEMP=str(path / 'remote'), ANSIBLE_ROLES_PATH=str(ROLE.parent),
                       ANSIBLE_NOCOLOR='1')
            args = ['ansible-playbook', '-i', str(inventory), str(book), '--tags', tags, '--check']
            if limit:
                args.extend(['--limit', limit])
            result = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, timeout=30)
            if expect_ok:
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn('failed=0', result.stdout)
            else:
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn('Exactly one execution host must remain after hosts and --limit', result.stdout)
            self.assertNotIn('Check the installed kubectl', result.stdout)

    def test_explicit_host_and_localhost(self):
        for host in ('node1', 'localhost', ['node1']):
            with self.subTest(host=host):
                self.run_selector(host, expect_ok=True)

    def test_localhost_selected_with_limit(self):
        self.run_selector('all', limit='localhost', include_localhost=True, expect_ok=True)

    def test_selectors_are_allowed_when_one_host_remains(self):
        for hosts in ('single', ['single'], 'node1*'):
            with self.subTest(hosts=hosts):
                self.run_selector(hosts, expect_ok=True)
        for hosts in ('multiple', 'all', 'node*', ['node1', 'node2'], 'node1,node2'):
            with self.subTest(hosts=hosts):
                self.run_selector(hosts, limit='node1', expect_ok=True)
        self.run_selector('all', limit='single', expect_ok=True)
        self.run_selector('all', limit='!node2', expect_ok=True)

    def test_multiple_effective_hosts_are_rejected(self):
        for hosts in ('multiple', 'all', 'node*', ['node1', 'node2'], 'node1,node2'):
            with self.subTest(hosts=hosts):
                self.run_selector(hosts)
        for limit in ('multiple', 'node*', 'node1,node2'):
            with self.subTest(limit=limit):
                self.run_selector('all', limit=limit)

    def test_serial_one_does_not_allow_multiple_hosts(self):
        self.run_selector('node1,node2', serial=1)
        self.run_selector('all', limit='node1', serial=1, expect_ok=True)

    def test_config_tag_cannot_skip_target_guard(self):
        self.run_selector('all', tags='config')

    def test_templated_target_host_is_validated(self):
        self.run_selector('{{ target_host }}', target='node1', expect_ok=True)
        self.run_selector('{{ target_host }}', target='single', expect_ok=True)
        self.run_selector('{{ target_host }}', target='multiple')


if __name__ == '__main__':
    unittest.main()
