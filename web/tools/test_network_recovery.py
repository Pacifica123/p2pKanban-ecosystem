"""Regression for build-failure classification and feature/lock consistency."""
import importlib.util
import sys
import tomllib
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import resilient_bootstrap as bootstrap

class RecoveryTests(unittest.TestCase):
    def test_compile_error_is_not_retried_even_with_registry_tls_lines(self):
        log = 'TLS handshake timeout during registry lookup\nerror[E0599]: no method named json\nerror: could not compile p2p-planner-backend'
        self.assertFalse(bootstrap.retryable(log))
        self.assertTrue(bootstrap.retryable('TLS handshake timeout'))
        self.assertFalse(bootstrap.retryable('error: the lock file needs to be updated\n503'))

    def test_json_feature_is_bound_in_the_locked_dependency_graph(self):
        manifest = tomllib.loads((ROOT / 'backend/Cargo.toml').read_text())
        self.assertIn('json', manifest['dependencies']['reqwest']['features'])
        lock = tomllib.loads((ROOT / 'backend/Cargo.lock').read_text())
        reqwest = next(p for p in lock['package'] if p['name'] == 'reqwest')
        self.assertIn('serde_json', reqwest['dependencies'])
        self.assertIn('serde', reqwest['dependencies'])

if __name__ == '__main__':
    unittest.main()
