# Build It: local AWS demonstration

No AWS account, billing setup, real AWS keys, or cloud deployment is needed.
The existing FastAPI application remains the main application. This small sidecar
demonstration runs the same Isolation Forest and trust engine in a Lambda-compatible
handler, using SAM's local runtime. Each successful invocation writes its result
to LocalStack S3, and the demo script reads it back to verify the invocation.

```text
PowerShell POST -> SAM local API :3001 -> Lambda container
                                          |
                               Existing PulseTrust trust engine
                                          |
                               LocalStack S3 :4566
                                          |
                            latest.json invocation evidence
```

SAM runs Lambda; LocalStack runs S3. This is not a Lambda deployed inside
LocalStack, and it is not a cloud deployment. No API Gateway/CloudFormation service
emulator, AWS CLI, SAM wrapper, or database replacement is necessary.

## Windows prerequisites

1. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/),
   enable its WSL 2 backend, and start **Linux containers**.
2. Install [AWS SAM CLI for Windows](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
   using the Windows installer. Open a new PowerShell terminal afterward.
3. Verify `docker info`, `docker compose version`, and `sam --version` succeed.
   Initial image/package downloads require internet access, but no AWS login.

Python is not required on the host for the container demo. Docker builds a Python
3.12 Lambda image with inference dependencies only. The image copies the existing
backend Python source and committed model; `.env`, virtual environments, and
credentials are excluded by the root `.dockerignore`. Lambda's Python 3.12 image
uses the newer Linux base needed for this model's scientific dependencies.

LocalStack is pinned to legacy Community `4.12.0` deliberately. Current releases
require a LocalStack auth token. LocalStack recommends pinning the legacy image
for continuing Community use: [official announcement](https://blog.localstack.cloud/the-road-ahead-for-localstack/).
Do not change this to `latest` for this account-free demo. No LocalStack token is
required for the pinned Community S3 service. This local prototype uses an older
emulator release and binds its port to loopback only.

## Start and demonstrate

Run from the repository root in PowerShell:

```powershell
.\local-aws\start.ps1
```

The script starts LocalStack, waits for S3, creates `pulsetrust-local-results`, builds
the SAM image, and runs the SAM HTTP listener in the foreground. Wait for the
listener to report it is running on port 3001. If local script execution is disabled,
use `powershell -ExecutionPolicy Bypass -File .\local-aws\start.ps1` for this process.

In a second PowerShell terminal, also at the repository root:

```powershell
.\local-aws\invoke.ps1
```

The command prints the real trust result from the committed model, including
`trust_score`, `state`, sensor evidence, agreement, an execution timestamp/request
ID, and a LocalStack archive location. It then checks the stored object's request
ID matches the invocation. A failed archive causes an error rather than a success
claim. Subsequent calls overwrite `latest.json`; this is demo evidence, not a new
production history store.

Other scenarios:

```powershell
.\local-aws\invoke.ps1 -Scenario sensor-failure
.\local-aws\invoke.ps1 -Scenario real-event
```

For telemetry input, create an event file with 5-100 readings in chronological
order, oldest first, from one device. Only `temp_1` and `temp_2` are required;
`device_id` is optional. Values must be finite JSON numbers.

```powershell
@{
    telemetry = @(
        @{temp_1=28.5; temp_2=28.6},
        @{temp_1=28.6; temp_2=28.7},
        @{temp_1=28.7; temp_2=28.8},
        @{temp_1=28.6; temp_2=28.7},
        @{temp_1=28.8; temp_2=28.9}
    )
} | ConvertTo-Json -Depth 5 | Set-Content -Encoding ascii "$env:TEMP\pulsetrust-event.json"
.\local-aws\invoke.ps1 -EventFile "$env:TEMP\pulsetrust-event.json"
```

Demo scenarios return `mode: SIMULATION`; supplied readings return `mode:
LOCAL_INPUT`. Neither reads nor writes Supabase or calls Gemini. The adapter
imports the shared trust engine rather than the FastAPI application. Existing
FastAPI/Supabase/Gemini behavior is unchanged.

## Visible evidence in FastAPI

Start FastAPI normally, with its existing environment configuration. Then open:

```text
http://127.0.0.1:8080/api/aws/status
```

This probes the loopback LocalStack and SAM listeners and reads the most recently
archived result. It returns `localstack_reachable`, `sam_reachable`, `active`,
`invocation_verified`, and `last_invocation`. An offline environment returns false
flags, not a fabricated active status. `last_invocation` is historical evidence:
inspect its timestamp; it does not imply a new invocation happened during the
status request. SAM reachability is an HTTP listener probe, not an inference test.

FastAPI still needs its existing Gemini configuration at startup; the separate
local AWS demo does not. No frontend files were changed. The status route is also
available through Swagger `/docs`.

## Stop and reset

Press Ctrl+C in the start terminal to stop SAM. Stop LocalStack with:

```powershell
docker compose -f .\local-aws\compose.yaml down
```

S3 storage is ephemeral and is removed with the container. To rebuild after a code
change, stop SAM and rerun the start script. Ports 3001 and 4566 must be available.
If startup fails, inspect `docker compose -f .\local-aws\compose.yaml logs`.

## Safety and scope

- Commands use `sam build` and `sam local start-api`; never `sam deploy`.
- SAM receives temporary dummy `test` signing values instead of real credentials;
  the script restores the process environment when it exits. These values are
  local placeholders, not AWS credentials or a requirement to configure an account.
- The adapter's S3 calls use fixed local endpoints, unsigned requests accepted by
  Community LocalStack, and no inherited HTTP proxy or AWS credential lookup.
- LocalStack does not receive the Docker socket. SAM manages the Lambda container.
- The SAM template defines the function and local HTTP event. S3 bucket creation
  is handled by the start script because SAM local does not provision resources.
- Existing App Runner files remain an optional future Ship It deployment path.

The setup uses [SAM local API emulation](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/using-sam-cli-local-start-api.html).
Confirm the hackathon's submission/evidence requirements against its official
rules; this repository demonstrates local tooling, not a cloud deployment.

## Tests and verification limits

From `backend`, using the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app tests
```

Tests compare the adapter with existing API and direct trust-engine output,
validate inputs, verify archive failures, exercise online/offline status responses,
and check inference does not import database or Gemini clients. Storage and status
network operations are mocked in these tests. Docker/SAM are not installed in the
implementation environment, so actual image builds and the two-command container
demo remain to be run on a machine with those prerequisites.
