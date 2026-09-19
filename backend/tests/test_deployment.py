"""Deployment checks; no database calls or real API credentials required."""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Avoid constructing an authenticated external client during test collection.
with patch("google.genai.Client"):
    from app.main import app

import start
from app.trust.anomaly_detector import MODEL_PATH, detect_anomaly


class DeploymentTests(unittest.TestCase):
    def test_launcher_default_and_custom_port(self):
        for env, port in [({}, 8080), ({"PORT": "9090"}, 9090)]:
            with patch.dict(os.environ, env, clear=True), patch("start.uvicorn.run") as run:
                start.main()
                run.assert_called_once_with("app.main:app", host="0.0.0.0", port=port)

    def test_model_from_unrelated_working_directory(self):
        original = Path.cwd()
        expected = detect_anomaly([28.5, 28.6, 28.7, 28.6, 28.8])
        try:
            os.chdir(BACKEND / "tests")
            self.assertTrue(MODEL_PATH.is_file())
            self.assertEqual(expected, detect_anomaly([28.5, 28.6, 28.7, 28.6, 28.8]))
        finally:
            os.chdir(original)

    def test_health_root_and_simulations(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/").json()["project"], "PulseTrust_")
            self.assertEqual(client.get("/health").status_code, 200)
            for scenario in ["normal", "sensor-failure", "real-event"]:
                response = client.get(f"/api/trust/demo/{scenario}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["mode"], "SIMULATION")
                self.assertIn("trust_score", response.json())
            self.assertEqual(client.get("/api/trust/demo/unknown").status_code, 400)

    def test_amplify_cors(self):
        with TestClient(app) as client:
            for method in ["GET", "POST"]:
                response = client.options("/api/telemetry", headers={
                    "Origin": "https://main.example.amplifyapp.com",
                    "Access-Control-Request-Method": method,
                    "Access-Control-Request-Headers": "content-type",
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], "*")
                self.assertNotIn("access-control-allow-credentials", response.headers)

    def test_import_without_frontend(self):
        # Use a fresh interpreter to exercise startup when only /backend exists.
        code = """
from unittest.mock import patch
with patch('google.genai.Client'), patch('pathlib.Path.is_dir', return_value=False):
    from app.main import app
assert '/health' in [route.path for route in app.routes]
assert '/dashboard' not in [route.path for route in app.routes]
"""
        subprocess.run([sys.executable, "-c", code], cwd=BACKEND, check=True)


if __name__ == "__main__":
    unittest.main()
