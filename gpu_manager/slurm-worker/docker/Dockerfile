# 基于 NGC PyTorch 26.03-py3
FROM nvcr.io/nvidia/pytorch:26.03-py3

# 设置环境变量避免交互
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# 更新并安装必要工具 + slurmd
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    net-tools \
    iperf3 \
    speedtest-cli \
    sysstat \
    pciutils \
    fio \
    htop \
    nvtop \
    jq \
    vim \
    git \
    unzip \
    munge \
    libmunge-dev \
    slurmd \
    slurm-client \
    && rm -rf /var/lib/apt/lists/*

# 创建 Slurm 所需目录
RUN mkdir -p /etc/slurm \
    /var/spool/slurmd \
    /var/log/slurm \
    /var/run/munge \
    && chmod 755 /var/spool/slurmd \
    && chmod 755 /var/log/slurm

# 配置 slurmd (计算节点配置，连接到外部控制节点)
# 实际使用时需要覆盖此文件或通过 volume 挂载
COPY <<-"EOF" /etc/slurm/slurm.conf
# Slurm compute node configuration
# 实际部署时请根据厂商提供的配置替换
ClusterName=ai-cluster
SlurmctldHost=slurmctld  # 替换为实际控制节点地址
AuthType=auth/munge
ProctrackType=proctrack/linuxproc
ReturnToService=2
SlurmdPidFile=/var/run/slurmd.pid
SlurmdLogFile=/var/log/slurm/slurmd.log
SlurmdSpoolDir=/var/spool/slurmd
# 节点配置（由控制节点动态下发，此处仅为占位）
NodeName=localhost CPUs=1 State=UNKNOWN
PartitionName=debug Nodes=localhost Default=YES State=UP
EOF

# 安装新版 Codex CLI
#RUN curl -fsSL https://codexcli.ai/install.sh | sh

# 安装 Claude Code CLI
#RUN curl -fsSL https://claude.ai/code/install.sh | sh

# 创建性能测试脚本目录
WORKDIR /opt/benchmark

# 编写 GPU 带宽测试脚本
COPY <<-"EOF" /opt/benchmark/gpu_bandwidth.sh
#!/bin/bash
echo "========== GPU Bandwidth Report =========="
date

echo "--- Per-GPU Memory Bandwidth ---"
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=index,name,memory.total,memory.bandwidth --format=csv,noheader 2>/dev/null || \
    nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader
else
    echo "nvidia-smi not found (no GPU available)"
fi

echo ""
echo "--- Per-GPU NVLink Bandwidth ---"
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi nvlink --status 2>/dev/null || echo "No NVLink detected"
    echo ""
    nvidia-smi nvlink --bandwidth 2>/dev/null || echo "NVLink bandwidth info not available"
else
    echo "No GPU/NVLink available"
fi
EOF

# 编写 PCIe 带宽测试脚本
COPY <<-"EOF" /opt/benchmark/pcie_bandwidth.sh
#!/bin/bash
echo "========== PCIe Bandwidth Report =========="
date

echo "--- PCIe Lanes Count ---"
lspci -vv 2>/dev/null | grep -E "VGA|3D|Display" -A 10 | grep -E "LnkCap|LnkSta" | head -10 || echo "No PCIe GPU information found"

echo ""
echo "--- Per-GPU PCIe Link Info ---"
if command -v nvidia-smi &> /dev/null; then
    echo "GPU Index, PCIe Gen, PCIe Width"
    nvidia-smi --query-gpu=index,pcie.link.gen.current,pcie.link.width.current --format=csv,noheader 2>/dev/null || echo "No GPU PCIe info"
fi
EOF

# 编写网络带宽测试脚本
COPY <<-"EOF" /opt/benchmark/internet_speed.sh
#!/bin/bash
echo "========== Internet Bandwidth Report =========="
date

echo "--- Upload / Download Speed ---"
if command -v speedtest-cli &> /dev/null; then
    speedtest-cli --simple 2>/dev/null || echo "Speed test failed"
else
    echo "speedtest-cli not installed"
    curl -o /dev/null -s -w "Download speed: %{speed_download} bytes/sec\n" \
        --max-time 30 https://speed.cloudflare.com/__down?bytes=100000000 2>/dev/null || echo "Network test failed"
fi

echo ""
echo "--- Latency to major sites ---"
for site in huggingface.co cloudflare.com aws.amazon.com openai.com google.com; do
    echo -n "$site: "
    ping -c 2 -W 3 $site 2>/dev/null | grep -o 'avg = [0-9.]*' | cut -d' ' -f3 || echo "timeout"
done
EOF

# 编写磁盘带宽测试脚本
COPY <<-"EOF" /opt/benchmark/disk_bandwidth.sh
#!/bin/bash
echo "========== Disk Bandwidth Report =========="
date

echo "--- Disk Information ---"
df -h | grep -v tmpfs | grep -v loop

echo ""
echo "--- Sequential Read Bandwidth ---"
if command -v fio &> /dev/null; then
    fio --name=seq_read --rw=read --size=512M --bs=1M --direct=1 --output-format=json 2>/dev/null | \
        jq -r '.jobs[0].read.bw' 2>/dev/null | xargs -I {} echo "Read Bandwidth: {} KB/s ($(echo "scale=2; {}/1024/1024" | bc 2>/dev/null) GB/s)"
else
    dd if=/dev/zero of=/tmp/test bs=1M count=512 2>&1 | grep -o "[0-9.]* MB/s" | head -1
fi

echo ""
echo "--- Sequential Write Bandwidth ---"
if command -v fio &> /dev/null; then
    fio --name=seq_write --rw=write --size=512M --bs=1M --direct=1 --output-format=json 2>/dev/null | \
        jq -r '.jobs[0].write.bw' 2>/dev/null | xargs -I {} echo "Write Bandwidth: {} KB/s ($(echo "scale=2; {}/1024/1024" | bc 2>/dev/null) GB/s)"
fi
EOF

# 编写外网可达性测试脚本
COPY <<-"EOF" /opt/benchmark/external_reachability.sh
#!/bin/bash
echo "========== External Reachability Report =========="
date
echo "Testing direct connectivity (no mirror):"

check_reachable() {
    local url=$1
    local name=$2
    local http_code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$url" 2>/dev/null)
    if [[ "$http_code" =~ ^2[0-9][0-9]$ ]] || [[ "$http_code" =~ ^3[0-9][0-9]$ ]]; then
        echo "✓ $name: OK (HTTP $http_code)"
    else
        echo "✗ $name: FAILED (HTTP $http_code)"
    fi
}

check_reachable "https://huggingface.co" "Hugging Face"
check_reachable "https://cloudflare.com" "Cloudflare"
check_reachable "https://aws.amazon.com" "AWS"
check_reachable "https://openai.com" "OpenAI"
check_reachable "https://google.com" "Google"
EOF

# 编写 slurmd 状态检查脚本
COPY <<-"EOF" /opt/benchmark/slurmd_status.sh
#!/bin/bash
echo "========== Slurmd Status Report =========="
date

echo "--- Slurmd Service ---"
if pgrep -x "slurmd" > /dev/null; then
    echo "slurmd: RUNNING (PID: $(pgrep -x slurmd))"
else
    echo "slurmd: NOT RUNNING"
fi

echo ""
echo "--- Munge Status ---"
if pgrep -x "munged" > /dev/null; then
    echo "munged: RUNNING"
else
    echo "munged: NOT RUNNING (required for slurmd authentication)"
fi

echo ""
echo "--- Slurm Node Info ---"
if command -v sinfo &> /dev/null; then
    sinfo -N 2>/dev/null || echo "Cannot connect to slurmctld (control node may not be reachable)"
fi

echo ""
echo "--- Slurmd Log (last 5 lines) ---"
if [ -f /var/log/slurm/slurmd.log ]; then
    tail -5 /var/log/slurm/slurmd.log 2>/dev/null || echo "No log content"
else
    echo "Log file not found"
fi
EOF

# 编写启动 slurmd 的脚本（可选，如果厂商需要自启动）
COPY <<-"EOF" /opt/benchmark/start_slurmd.sh
#!/bin/bash
# 启动 munge (认证服务)
if ! pgrep -x "munged" > /dev/null; then
    echo "Starting munged..."
    /usr/sbin/munged --force --num-threads=10 2>/dev/null || true
    sleep 1
fi

# 启动 slurmd
if ! pgrep -x "slurmd" > /dev/null; then
    echo "Starting slurmd..."
    /usr/sbin/slurmd -D 2>/dev/null &
    sleep 2
    echo "slurmd started (PID: $(pgrep -x slurmd 2>/dev/null || echo 'unknown'))"
else
    echo "slurmd already running"
fi
EOF

# 编写综合测试脚本（自启动执行）
COPY <<-"EOF" /opt/benchmark/run_all_benchmarks.sh
#!/bin/bash
REPORT_DIR="/opt/benchmark/reports"
mkdir -p $REPORT_DIR
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="$REPORT_DIR/benchmark_report_$TIMESTAMP.txt"

echo "====================================================" | tee $REPORT_FILE
echo "       AI Infrastructure Benchmark Report          " | tee -a $REPORT_FILE
echo "====================================================" | tee -a $REPORT_FILE
echo "Timestamp: $(date)" | tee -a $REPORT_FILE
echo "Hostname: $(hostname)" | tee -a $REPORT_FILE
echo "====================================================" | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

# 收集系统信息
echo "--- System Information ---" | tee -a $REPORT_FILE
echo "Ubuntu Version: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)" | tee -a $REPORT_FILE
echo "Kernel: $(uname -r)" | tee -a $REPORT_FILE
echo "CUDA Version: $(nvcc --version 2>/dev/null | grep 'release' | awk '{print $6}' | tr -d ',' || echo 'N/A')" | tee -a $REPORT_FILE
echo "PyTorch Version: $(python3 -c 'import torch; print(torch.__version__)' 2>/dev/null || echo 'N/A')" | tee -a $REPORT_FILE
echo "Slurmd Version: $(slurmd -V 2>/dev/null | head -1 || echo 'N/A')" | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

# 可选：启动 slurmd（注释掉，通常由厂商系统管理）
# bash /opt/benchmark/start_slurmd.sh 2>&1 | tee -a $REPORT_FILE
# echo "" | tee -a $REPORT_FILE

# 运行各项测试
bash /opt/benchmark/slurmd_status.sh | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

bash /opt/benchmark/gpu_bandwidth.sh | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

bash /opt/benchmark/pcie_bandwidth.sh | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

bash /opt/benchmark/internet_speed.sh | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

bash /opt/benchmark/disk_bandwidth.sh | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

bash /opt/benchmark/external_reachability.sh | tee -a $REPORT_FILE
echo "" | tee -a $REPORT_FILE

echo "====================================================" | tee -a $REPORT_FILE
echo "Report saved to: $REPORT_FILE" | tee -a $REPORT_FILE
echo "====================================================" | tee -a $REPORT_FILE

# 保持容器运行
echo ""
echo "All benchmarks completed."
EOF

# 设置可执行权限
RUN chmod +x /opt/benchmark/*.sh

# 暴露 slurmd 端口
EXPOSE 6818

# 容器启动入口
#ENTRYPOINT ["/opt/benchmark/run_all_benchmarks.sh"]

# 默认保持运行
CMD ["tail", "-f", "/dev/null"]
