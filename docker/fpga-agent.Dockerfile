# syntax=docker/dockerfile:1

FROM python:3.13-slim AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    FPGA_AGENT_SOCKET=/run/fpga-agent/fpga-agent.sock \
    FPGA_AGENT_VIVADO_SETTINGS=/opt/Xilinx/2025.2/Vivado/settings64.sh \
    FPGA_AGENT_XSDB=xsdb \
    FPGA_AGENT_VIVADO=vivado

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates libusb-1.0-0 udev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src src

RUN pip install --no-cache-dir .

VOLUME ["/run/fpga-agent"]
CMD ["python", "-m", "fpga_agent.main"]
