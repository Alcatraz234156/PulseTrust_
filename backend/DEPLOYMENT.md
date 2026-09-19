App Runner source deployment
============================

- Repository source directory: `/backend`.
- Configuration source: **Use a configuration file** (`apprunner.yaml`).
- Runtime: Python 3.11 (`python311`).
- Build command: `python3 -m compileall -q app start.py`.
- Pre-run commands: `pip3 install --no-cache-dir -r requirements.txt`, then `pip3 check`.
- Start command: `python3 start.py`.
- Application: `app.main:app`, listening on `0.0.0.0`.
- Network port: `8080`, exported as `PORT`. The launcher defaults to 8080 outside App Runner.
- Health check: HTTP, path `/health` (configure in the App Runner service console).

Do not replace the pre-run installation with a build-only global pip install:
the Python 3.11 revised build discards packages installed outside `/app` during
the build phase. See [AWS Python runtime documentation](https://docs.aws.amazon.com/apprunner/latest/dg/service-source-code-python.html).

Configure runtime secrets in App Runner using Secrets Manager or SSM references
and an instance role with access to those secrets:

- `SUPABASE_URL` and `SUPABASE_KEY` for existing telemetry storage.
- `GEMINI_API_KEY` for the existing Gemini client (required at application import).
- `MOUSER_API_KEY` for component lookup when used.
- `NEXAR_CLIENT_ID` and `NEXAR_CLIENT_SECRET` only if using the Nexar integration.

Never put secret values in the YAML, source code, or committed `.env` files.
No secrets are required for the compile-only build. `/health` reports configuration
presence; it does not probe database availability.

The committed `models/temperature_isolation_forest.joblib` must be included in
the deployment. Model loading and training output use paths relative to backend
source, regardless of the working directory. Do not retrain during deployment.
The scikit-learn pin matches the local environment that loads the existing model.
NumPy and SciPy permit Python 3.11-compatible releases rather than requiring the
Python 3.12+ versions installed in the developer environment.

CORS allows all origins with credentials disabled for this hackathon deployment.
The API works without the frontend directory; `/dashboard` is still mounted when
that directory exists. No frontend deployment changes are included.

Local verification from `backend`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe start.py
```

Use Python 3.11 in CI or App Runner to validate dependency resolution and model
inference on the target runtime before directing the frontend to the new service.

Verification performed: five deployment tests, Python compilation, local `pip
check`, YAML parsing, and a Linux CPython 3.11 dependency-resolution dry run using
manylinux 2.28 and manylinux2014 wheels. The local interpreter is Python 3.14;
this is not a completed App Runner deployment or a Python 3.11 inference test.
The existing scikit-learn 1.9.1 Linux wheels require glibc 2.27 or newer. Verify
the selected App Runner image supports these wheels; an older image may attempt
a source build. Do not downgrade scikit-learn or regenerate the model to bypass
that constraint without validating model compatibility.
