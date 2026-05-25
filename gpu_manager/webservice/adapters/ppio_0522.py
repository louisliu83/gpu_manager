import requests
import time
import logging
from typing import List, Dict, Any
from .base import BaseProvider

logger = logging.getLogger(__name__)

class PPIOModel(BaseProvider):
    """派欧云 GPU 实例适配器"""
    
    def __init__(self, api_key: str, controller_ip: str):
        self.base_url = "https://api.ppio.com/gpu-instance/openapi/v1"
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.controller_ip = controller_ip
    
    def get_available_gpus(self) -> List[Dict[str, Any]]:
        """获取可用 GPU 列表"""
        try:
            resp = requests.get(f"{self.base_url}/products?clusterId=27", headers=self.headers, timeout=10)
            data = resp.json()
            logger.info(data)
            available_gpus = []
            for gpu in data.get("data", []):
                available_gpus.append({"type": gpu.get("name", ""), "price": gpu.get("price", ""), "available": True, "provider": "ppio"})
            return available_gpus
        except Exception as e:
            logger.error(f"Failed to fetch GPU list: {e}")
            return []
    
    def _build_user_data(self, gpu_num: int) -> str:
        """构建实例 User Data 脚本"""
        return f"""#!/bin/bash
set -e
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y slurmd munge curl

mkdir -p /etc/munge
dd if=/dev/urandom of=/etc/munge/munge.key bs=1024 count=1
chmod 400 /etc/munge/munge.key
chown munge:munge /etc/munge/munge.key
service munge start

cat > /etc/slurm/slurm.conf <<EOF
ClusterName=gpu-cluster
ControlMachine={self.controller_ip}
AuthType=auth/munge
SlurmdPort=6818
SelectType=select/cons_tres
GresTypes=gpu
EOF

mkdir -p /var/spool/slurmd /var/log/slurm
chown slurm:slurm /var/spool/slurmd /var/log/slurm
slurmd -Z --conf "RealMemory=64000 Gres=gpu:nvidia:{gpu_num}"
sleep infinity
"""
    
    def launch_instance(self, gpu_type: str, gpu_num: int = 1,
                        disk_size: int = 100, spot: bool = False, **kwargs) -> Dict[str, Any]:
        """创建 GPU 实例"""
        payload = {
            "gpu_type": gpu_type,
            "gpu_count": gpu_num,
            "disk_size_gb": disk_size,
            "image": "ubuntu:24.04",
            "spot": spot,
            "user_data": self._build_user_data(gpu_num)
        }
        
        try:
            resp = requests.post(f"{self.base_url}/gpu/instance/create", json=payload,
                                 headers=self.headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return {
                "instance_id": data["instance_id"],
                "provider": "ppio",
                "gpu_type": gpu_type,
                "status": "creating"
            }
        except Exception as e:
            logger.error(f"Failed to launch PPIO instance: {e}")
            raise
    
    def terminate_instance(self, instance_id: str) -> bool:
        try:
            resp = requests.delete(f"{self.base_url}/instances/{instance_id}",
                                   headers=self.headers, timeout=30)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Failed to terminate: {e}")
            return False
    
    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        try:
            resp = requests.get(f"{self.base_url}/instances/{instance_id}",
                                headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return {"status": data.get("status", "unknown"), "ip": data.get("ip")}
            return {"status": "unknown", "ip": None}
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return {"status": "error", "ip": None}
    
    def get_instance_metrics(self, instance_id: str) -> Dict[str, Any]:
        try:
            resp = requests.get(f"{self.base_url}/instances/{instance_id}/metrics",
                                headers=self.headers, timeout=10)
            return resp.json() if resp.status_code == 200 else {}
        except Exception:
            return {}
