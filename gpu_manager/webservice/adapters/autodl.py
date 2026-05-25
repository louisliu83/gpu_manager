# adapters/autodl.py
import requests
import time
import logging
from typing import List, Dict, Any
from .base import BaseProvider

logger = logging.getLogger(__name__)

class AutoDLProvider(BaseProvider):
    """AutoDL 弹性部署 API 适配器"""
    
    def __init__(self, api_token: str, controller_ip: str):
        self.base_url = "https://private.autodl.com"
        self.headers = {"Authorization": api_token, "Content-Type": "application/json"}
        self.controller_ip = controller_ip
        
        # GPU 型号映射
        self.gpu_mapping = {
            "A100": ["NVIDIA-A100", "A100-PCIE-40GB"],
            "H100": ["NVIDIA-H100", "H100-PCIE-80GB"],
            "RTX4090": ["NVIDIA-RTX4090"],
            "A800": ["NVIDIA-A800"],
            "H800": ["NVIDIA-H800"],
        }
        
        # 预置镜像 UUID（需要从平台实际获取）
        self.image_mapping = {
            "ubuntu22.04-cuda12.4": "your-ubuntu-22.04-cuda-12.4-uuid",
            "pytorch2.5-cuda12.4": "your-pytorch-2.5-cuda-12.4-uuid",
        }
    
    def get_available_gpus(self) -> List[Dict[str, Any]]:
        """获取可用 GPU 列表（静态配置，API 需单独实现）"""
        return [
            {"type": "A100", "price": 4.5, "available": True, "provider": "autodl"},
            {"type": "H100", "price": 8.0, "available": True, "provider": "autodl"},
            {"type": "RTX4090", "price": 2.2, "available": True, "provider": "autodl"},
        ]
    
    def _build_slurmd_cmd(self, gpu_num: int, gpu_type: str) -> str:
        """构建 slurmd 初始化命令"""
        gpu_name_lower = gpu_type.lower().replace("rtx", "").replace("a100", "a100")
        mem_gb = 32 * gpu_num
        cpu_cores = 8 * gpu_num
        
        return f"""#!/bin/bash
set -e
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y slurmd munge curl sudo

# 配置 Munge
mkdir -p /etc/munge
dd if=/dev/urandom of=/etc/munge/munge.key bs=1024 count=1
chmod 400 /etc/munge/munge.key
chown munge:munge /etc/munge/munge.key
service munge start

# 配置 slurm.conf
cat > /etc/slurm/slurm.conf <<EOF
ClusterName=gpu-cluster
ControlMachine={self.controller_ip}
AuthType=auth/munge
CryptoType=crypto/munge
SlurmdPort=6818
SlurmUser=slurm
SlurmdUser=root
StateSaveLocation=/var/spool/slurmd
SelectType=select/cons_tres
GresTypes=gpu
NodeName=localhost CPUs=1 State=UNKNOWN
PartitionName=autodl Nodes=ALL Default=YES MaxTime=INFINITE State=UP
EOF

mkdir -p /var/spool/slurmd /var/log/slurm
chown slurm:slurm /var/spool/slurmd /var/log/slurm

slurmd -Z --conf "RealMemory={mem_gb * 1024} Gres=gpu:{gpu_name_lower}:{gpu_num}"
sleep infinity
"""
    
    def launch_instance(self, gpu_type: str, gpu_num: int = 1,
                        disk_size: int = 100, **kwargs) -> Dict[str, Any]:
        """创建部署，这里会调用 POST /api/v1/dev/deployment 接口[reference:5]"""
        gpu_name = self.gpu_mapping.get(gpu_type, [gpu_type])[0]
        image_uuid = self.image_mapping.get("ubuntu22.04-cuda12.4")
        
        payload = {
            "name": f"slurm-worker-{gpu_type}-{int(time.time())}",
            "deployment_type": "ReplicaSet",
            "replica_num": 1,
            "container_template": {
                "cuda_v": 12,
                "gpu_name_set": [gpu_name],
                "gpu_num": gpu_num,
                "memory_size_from": 32 * gpu_num,
                "memory_size_to": 32 * gpu_num,
                "cpu_num_from": 8 * gpu_num,
                "cpu_num_to": 8 * gpu_num,
                "price_from": 0,
                "price_to": 10000,
                "image_uuid": image_uuid,
                "cmd": self._build_slurmd_cmd(gpu_num, gpu_type)
            }
        }
        
        try:
            resp = requests.post(f"{self.base_url}/api/v1/dev/deployment",
                                 json=payload, headers=self.headers, timeout=(120, 300))
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "Success":
                return {
                    "instance_id": data["data"]["deployment_uuid"],
                    "provider": "autodl",
                    "gpu_type": gpu_type,
                    "status": "creating"
                }
            raise Exception(f"AutoDL API error: {data.get('msg')}")
        except Exception as e:
            logger.error(f"Failed to launch AutoDL instance: {e}")
            raise
    
    def terminate_instance(self, instance_id: str) -> bool:
        """删除部署"""
        try:
            resp = requests.post(f"{self.base_url}/api/v1/dev/deployment/delete",
                                 json={"deployment_uuid": instance_id},
                                 headers=self.headers, timeout=30)
            return resp.json().get("code") == "Success"
        except Exception as e:
            logger.error(f"Failed to terminate: {e}")
            return False
    
    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """查询容器事件获取状态，参考事件列表 API[reference:6]"""
        try:
            resp = requests.post(f"{self.base_url}/api/v1/dev/deployment/container/event/list",
                                 json={"deployment_uuid": instance_id, "page_index": 1, "page_size": 10},
                                 headers=self.headers, timeout=10)
            data = resp.json()
            if data.get("code") != "Success":
                return {"status": "unknown", "ip": None}
            
            events = data.get("data", {}).get("data", [])
            for event in events:
                status = event.get("status")
                ip = event.get("ip")
                if status == "running":
                    return {"status": "running", "ip": ip}
                elif status == "creating":
                    return {"status": "creating", "ip": None}
            return {"status": "unknown", "ip": None}
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return {"status": "error", "ip": None}
    
    def get_instance_metrics(self, instance_id: str) -> Dict[str, Any]:
        """获取监控指标"""
        return {}
