# gpu-platform/adapters/compshare.py
import hashlib
import json
import logging
import time
import urllib.parse
from typing import Dict, Any, List, Optional

import requests

from .base import BaseProvider

from ucloud.core import exc
from ucloud.client import Client

logger = logging.getLogger(__name__)

class CompShareProvider(BaseProvider):
    def __init__(self, public_key: str, private_key: str, controller_ip: Optional[str] = None):
        self.public_key = public_key
        self.private_key = private_key
        self.controller_ip = controller_ip
        self.base_url = "https://api.ucloud.cn/"

#    def _generate_signature(self, params: Dict[str, Any]) -> str:
#        """生成API签名，具体算法请参考UCloud官方签名文档。"""
#        sorted_params = sorted(params.items())
#        param_str = "&".join([f"{k}={v}" for k, v in sorted_params if v is not None])
#        sign_str = f"{param_str}{self.private_key}"
#        return hashlib.md5(sign_str.encode("utf-8")).hexdigest()

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        """UCloud API 签名 - SHA1 算法"""
        # 排除 Signature 字段本身
        params = {k: v for k, v in params.items() if k != "Signature" and v is not None}
        sorted_params = sorted(params.items())
        param_str = "".join([f"{k}{v}" for k, v in sorted_params])
        sign_str = f"{param_str}{self.private_key}"
        return hashlib.sha1(sign_str.encode("utf-8")).hexdigest()

    def _build_user_data(self, gpu_num: int, gpu_type: str) -> str:
        """生成实例启动脚本，用于将节点注册到Slurm控制器。"""
        if not self.controller_ip:
            return "echo 'No controller IP' && sleep infinity"
        mem_gb = 32 * gpu_num
        script = f"""#!/bin/bash
set -e
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y slurmd munge curl

mkdir -p /etc/munge
dd if=/dev/urandom of=/etc/munge/munge.key bs=1024 count=1 2>/dev/null
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
NodeName=localhost CPUs=1 State=UNKNOWN
PartitionName=compshare Nodes=ALL Default=YES MaxTime=INFINITE State=UP
EOF

mkdir -p /var/spool/slurmd /var/log/slurm
chown slurm:slurm /var/spool/slurmd /var/log/slurm
slurmd -Z --conf "RealMemory={mem_gb * 1024} Gres=gpu:{gpu_type}:{gpu_num}"
sleep infinity
"""
        import base64
        return base64.b64encode(script.encode()).decode()

    def get_available_gpus(self) -> List[Dict[str, Any]]:
        """查询可用GPU机型信息。"""
        try:
            params = {
                "Action": "DescribeAvailableCompShareInstanceTypes",
                "PublicKey": self.public_key,
                "Region": "cn-wlcb",
            }
            logger.info(params)
            params["Signature"] = self._generate_signature(params)
            resp = requests.get(self.base_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("RetCode") != 0:
                logger.error(f"API Error: {data.get('Message')}")
                return self._get_mock_gpu_list()

            gpu_list = []
            instance_types = data.get("InstanceTypes", [])
            for it in instance_types:
                if it.get("GPU", 0) > 0:
                    gpu_list.append({
                        "type": it.get("InstanceType", "Unknown"),
                        "price": 0.0,
                        "available": it.get("Status") == "Available",
                        "provider": "compshare",
                        "gpu_count": it.get("GPU", 0),
                        "cpu": it.get("CPU", 0),
                        "memory": it.get("Memory", 0) // 1024,
                    })
            return gpu_list
        except Exception as e:
            logger.error(f"Failed to get GPU list: {e}")
            return self._get_mock_gpu_list()

    def _get_mock_gpu_list(self) -> List[Dict[str, Any]]:
        """模拟GPU列表，供API不可用或测试时使用。"""
        return [
            {"type": "gpu.gn7.2xlarge", "price": 8.8, "available": True, "provider": "compshare"},
            {"type": "gpu.gn7.4xlarge", "price": 12.5, "available": True, "provider": "compshare"},
        ]

    def launch_instance(self, gpu_type: str, gpu_num: int = 1,
                        disk_size: int = 100, spot: bool = False, **kwargs) -> Dict[str, Any]:
        """创建GPU实例。"""
        if "Zone" not in kwargs or "CompShareImageId" not in kwargs:
            raise ValueError("必需参数 'Zone' 和 'CompShareImageId' 缺失。")
        # 确保用户脚本不超过16KB
        user_data = self._build_user_data(gpu_num, gpu_type)
        if len(user_data) > 16384:
            logger.warning("User data too long, may be truncated")
        params = {
            "Action": "CreateCompShareInstance",
            "PublicKey": self.public_key,
            "Region": "cn-zj",
            "Zone": kwargs["Zone"],
            "CompShareImageId": kwargs["CompShareImageId"],
            "MachineType": kwargs.get("MachineType", "G"),
            "GPU": gpu_num,
            "GpuType": gpu_type,
            "CPU": kwargs.get("CPU", 8),
            "Memory": kwargs.get("Memory", 32768),
            "Disks.0.IsBoot": "True",
            "Disks.0.Type": "CLOUD_SSD",
            "Disks.0.Size": str(disk_size),
            "Name": kwargs.get("Name", f"slurm-worker-{int(time.time())}"),
            "ChargeType": "Spot" if spot else kwargs.get("ChargeType", "Month"),
            "LoginMode": "Password",
            "Password": kwargs.get("Password", ""),
        }
        # 过滤None值，避免签名时出错
        params = {k: v for k, v in params.items() if v is not None}
        params["Signature"] = self._generate_signature(params)
        try:
            resp = requests.post(self.base_url, data=params, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            if data.get("RetCode") != 0:
                raise Exception(f"Create instance failed: {data.get('Message')}")
            instance_id = data.get("UHostIds", [None])[0]
            if not instance_id:
                raise Exception("API response did not contain UHostIds")
            return {
                "instance_id": instance_id,
                "provider": "compshare",
                "gpu_type": gpu_type,
                "status": "creating"
            }
        except Exception as e:
            logger.error(f"Failed to launch instance: {e}")
            raise

    def terminate_instance(self, instance_id: str) -> bool:
        """释放一个GPU实例。"""
        try:
            params = {
                "Action": "TerminateCompShareInstance",
                "PublicKey": self.public_key,
                "Region": "cn-zj",
                "UHostId": instance_id,
                "ReleaseUDisk": "True",
            }
            params["Signature"] = self._generate_signature(params)
            resp = requests.post(self.base_url, data=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return data.get("RetCode") == 0
        except Exception as e:
            logger.error(f"Failed to terminate instance {instance_id}: {e}")
            return False

    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """查询实例状态和IP地址。"""
        try:
            params = {
                "Action": "DescribeCompShareInstance",
                "PublicKey": self.public_key,
                "Region": "cn-zj",
                "UHostId": instance_id,
            }
            params["Signature"] = self._generate_signature(params)
            resp = requests.get(self.base_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("RetCode") != 0:
                raise Exception(f"Describe instance failed: {data.get('Message')}")
            instance_set = data.get("InstanceSet", [])
            if not instance_set:
                return {"status": "unknown", "ip": None}
            inst = instance_set[0]
            status_map = {
                "Initializing": "creating",
                "Running": "running",
                "Stopped": "stopped",
                "Terminated": "deleted",
            }
            return {
                "status": status_map.get(inst.get("State", "unknown"), "unknown"),
                "ip": inst.get("IPSet", [{}])[0].get("IP", None),
            }
        except Exception as e:
            logger.error(f"Failed to get instance status for {instance_id}: {e}")
            return {"status": "error", "ip": None}

    def get_instance_metrics(self, instance_id: str) -> Dict[str, Any]:
        """获取GPU监控指标。"""
        try:
            params = {
                "Action": "DescribeCompShareInstanceMetric",
                "PublicKey": self.public_key,
                "Region": "cn-zj",
                "UHostId": instance_id,
            }
            params["Signature"] = self._generate_signature(params)
            resp = requests.get(self.base_url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            return {
                "gpu_util": data.get("GPUUtilization"),
                "cpu_util": data.get("CPUUtilization"),
                "mem_util": data.get("MemUtilization"),
            }
        except Exception as e:
            logger.error(f"Failed to get metrics for instance {instance_id}: {e}")
            return {}
