# Container for MCP hosts that start servers in Docker (e.g. Smithery).
# The server reaches Live through ABLETON_HOST / ABLETON_PORT, so point
# ABLETON_HOST at the machine running Live (host.docker.internal on Docker
# Desktop) and allow it on the Live side with ABLETON_MCP_HOST.
FROM python:3.12-slim
WORKDIR /srv
COPY pyproject.toml README.md LICENSE ./
COPY ableton_studio_mcp ./ableton_studio_mcp
RUN pip install --no-cache-dir .
ENV ABLETON_HOST=host.docker.internal
ENTRYPOINT ["ableton-studio-mcp"]
