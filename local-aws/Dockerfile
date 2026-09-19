FROM public.ecr.aws/lambda/python:3.12
# Only inference dependencies; no Supabase/Gemini credentials or app startup.
COPY local-aws/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY backend/app ${LAMBDA_TASK_ROOT}/app
COPY backend/models/temperature_isolation_forest.joblib ${LAMBDA_TASK_ROOT}/models/temperature_isolation_forest.joblib
CMD ["app.aws_local.lambda_handler"]
