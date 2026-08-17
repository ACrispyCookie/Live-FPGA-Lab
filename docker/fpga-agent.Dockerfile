# syntax=docker/dockerfile:1

FROM python:3.13-slim-bookworm AS runtime
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONPATH=/app/src \
    FPGA_AGENT_SOCKET=/run/fpga-agent/fpga-agent.sock \
    FPGA_AGENT_VIVADO_SETTINGS=/opt/Xilinx/2025.2/Vivado/settings64.sh \
    FPGA_AGENT_XSDB=xsdb \
    FPGA_AGENT_VIVADO=vivado

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        fontconfig \
        libfreetype6 \
        libglib2.0-0 \
        libncurses5 \
        libpixman-1-0 \
        libtinfo5 \
        libusb-1.0-0 \
        libx11-6 \
        libxext6 \
        libxi6 \
        libxrender1 \
        libxtst6 \
        locales \
        udev \
    && sed -i 's/^# *\(en_US.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
    && locale-gen en_US.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src src

RUN pip install --no-cache-dir .

VOLUME ["/app/demos"]
VOLUME ["/run/fpga-agent"]
CMD ["python", "-m", "fpga_agent.main"]
