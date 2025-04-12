# See here for image contents: https://github.com/microsoft/vscode-dev-containers/tree/v0.344.0/containers/python-3/.devcontainer/base.Dockerfile

ARG VARIANT="3.13"
FROM mcr.microsoft.com/devcontainers/python:${VARIANT}

# Install git
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends git

# Install uv
RUN pip install uv

# [Optional] Uncomment this line to install additional packages. Requires pipx
# RUN pipx install poetry

# [Optional] Uncomment this line to install global node packages.
# RUN su vscode -c "source /usr/local/share/nvm/nvm.sh && npm install -g <your-package-here>"
