import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_deployment import app
from fastapi.testclient import TestClient
from app.aws_local import analyze_input, integration_status, lambda_handler
from app.trust.trust_engine import calculate_temperature_trust


class LocalAwsTests(unittest.TestCase):
    def test_demo_matches_existing_api(self):
        with TestClient(app) as client:
            for scenario in ('normal', 'sensor-failure', 'real-event'):
                self.assertEqual(analyze_input({'scenario': scenario}),
                                 client.get(f'/api/trust/demo/{scenario}').json())

    def test_supplied_telemetry_uses_existing_engine(self):
        rows = [{'temp_1': 28 + i / 10, 'temp_2': 28.1 + i / 10} for i in range(8)]
        expected = calculate_temperature_trust([r['temp_1'] for r in rows], [r['temp_2'] for r in rows])
        self.assertEqual(analyze_input({'telemetry': rows}), {'mode': 'LOCAL_INPUT', **expected})

    def test_invalid_inputs(self):
        for payload in ([], {'scenario': 'missing'}, {'telemetry': []},
                        {'telemetry': [{'temp_1': float('nan'), 'temp_2': 20}] * 5},
                        {'telemetry': [{'temp_1': True, 'temp_2': 20}] * 5},
                        {'telemetry': [{'temp_1': 20}] * 5},
                        {'telemetry': [], 'scenario': 'normal'},
                        {'telemetry': [{'device_id': str(i), 'temp_1': 20, 'temp_2': 20} for i in range(5)]}):
            self.assertEqual(lambda_handler(payload, None)['statusCode'], 400)
        self.assertEqual(lambda_handler({'body': '{invalid'}, None)['statusCode'], 400)

    def test_archive_and_http_event(self):
        with patch.dict(os.environ, {'PULSETRUST_LOCAL_ARCHIVE': '1'}), patch('app.aws_local.local_request') as request:
            response = lambda_handler({'body': '{"scenario":"real-event"}'}, None)
            self.assertEqual(response['statusCode'], 200)
            request.assert_called_once()
            args, kwargs = request.call_args
            self.assertEqual(args[0], 'http://localstack:4566/pulsetrust-local-results/latest.json')
            self.assertEqual(kwargs['method'], 'PUT')
            stored = json.loads(kwargs['data'])
            result = json.loads(response['body'])
            self.assertEqual(stored['trust_score'], result['trust_score'])
            self.assertEqual(result['archive']['provider'], 'LocalStack S3')

    def test_archive_failure_is_not_success(self):
        with patch.dict(os.environ, {'PULSETRUST_LOCAL_ARCHIVE': '1'}), patch('app.aws_local.local_request', side_effect=OSError):
            response = lambda_handler({'scenario': 'normal'}, None)
            self.assertEqual(response['statusCode'], 503)
            self.assertIn('trust_result', json.loads(response['body']))

    def test_status_offline_and_online(self):
        with patch('app.aws_local.local_request', side_effect=OSError):
            with TestClient(app) as client:
                result = client.get('/api/aws/status').json()
            self.assertFalse(result['active'])
            self.assertFalse(result['invocation_verified'])
        with patch('app.aws_local.local_request', side_effect=[b'{}', b'{"trust_score":100}', b'{}']):
            result = integration_status()
            self.assertTrue(result['active'])
            self.assertTrue(result['invocation_verified'])

    def test_inference_import_does_not_initialize_external_services(self):
        code = """
import sys
from app.aws_local import analyze_input
assert analyze_input({'scenario': 'normal'})['mode'] == 'SIMULATION'
assert 'app.database' not in sys.modules
assert 'app.main' not in sys.modules
assert 'google.genai' not in sys.modules
"""
        subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1], check=True)


if __name__ == '__main__':
    unittest.main()
