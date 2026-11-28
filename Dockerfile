# mail2apprise serve: the SMTP sink, one standard-library file on the
# official Python image. Nothing to build or install.
FROM python:3.15.2-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
# The CI pipeline adds org.opencontainers.image.source and .revision, and
# .version from the release tag (pyproject.toml's version is a placeholder).
LABEL org.opencontainers.image.title="mail2apprise" \
      org.opencontainers.image.description="SMTP sink and Postfix pipe transport that turns a mail into an Apprise notification" \
      org.opencontainers.image.licenses="MIT"
# Nothing is written at run time, so the root filesystem can be read-only.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
# The base image's pip (with the packages it vendors) and ensurepip's
# bundled pip wheel are never used at run time; removing them keeps their
# CVEs out of the image.
RUN /usr/local/bin/python3 -m pip uninstall -y --root-user-action=ignore pip \
    && rm -rf /usr/local/lib/python3*/ensurepip
# The distribution's security fixes published since the base image was
# built: Docker's official images are rebuilt only every week or few.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*
COPY src/mail2apprise/__init__.py /usr/local/bin/mail2apprise
# Unprivileged: 2525 needs no capability; a Service or a firewall maps 25.
USER 65534:65534
EXPOSE 2525
ENTRYPOINT ["python3", "/usr/local/bin/mail2apprise"]
CMD ["serve"]
