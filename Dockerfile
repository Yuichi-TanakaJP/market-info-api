# Keep the Python base image reproducible. Refresh this digest intentionally
# together with the dependency lock files.
FROM python:3.11.18-slim@sha256:ffe4b0c76963e64f05484d74dbb3f67fad1effcf3c5c22c2235f0fafc8a9c98f

WORKDIR /app

# Bootstrap patched pip with the hash published by Python security-announce.
# pip vendors its own CA bundle independently of the runtime certifi package.
RUN python -m pip install --no-cache-dir "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY app/ ./app/
RUN python -m compileall -q /app/app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
