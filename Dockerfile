FROM python:3.13-slim-trixie

ARG UID=1018
ARG GID=1018
ARG APPDIR="/srv/app"
ARG USER="flaskapp"

RUN apt-get update \
  && apt-get install -y --no-install-recommends passwd \
  && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man \
  && apt-get clean \
  && groupadd -g "${GID}" "${USER}" \
  && useradd -u "${UID}" -g "${GID}" "${USER}" \
  && mkdir "${APPDIR}" \
  && chown "${USER}:${USER}" -R "${APPDIR}"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

USER "${USER}"
WORKDIR "${APPDIR}"
COPY --chown="${USER}:${USER}" app .

ENV FLASK_DEBUG=false \
  FLASK_APP=okta-looker-scim-bridge \
  FLASK_SKIP_DOTENV=true \
  PYTHONUNBUFFERED=TRUE

EXPOSE 8080
CMD ["gunicorn", \
  "--preload", \
  "--workers", "1", "--threads", "8", "--timeout", "0", \
  "--error-logfile", "-", \
  "--access-logfile", "-", \
  "--bind", "[::]:8080", \
  "app:app" \
]
