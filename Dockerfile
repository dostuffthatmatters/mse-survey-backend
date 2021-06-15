FROM python:3.8

ARG commit_sha
ARG branch_name

LABEL maintainer="Felix Böhm <felix@felixboehm.dev>"
LABEL source="https://github.com/fastsurvey/backend"
LABEL commit_sha=${commit_sha}
LABEL branch_name=${branch_name}

ENV COMMIT_SHA=${commit_sha}
ENV BRANCH_NAME=${branch_name}

RUN pip install --upgrade pip
RUN pip install poetry
RUN poetry config virtualenvs.create false

COPY pyproject.toml pyproject.toml
RUN poetry install --no-dev

EXPOSE 8000

COPY /app /app

CMD uvicorn app.main:app --host 0.0.0.0 --port 8000
