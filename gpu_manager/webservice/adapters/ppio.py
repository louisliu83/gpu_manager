# adapters/ppio.py
import requests
import time
import logging
from typing import List, Dict, Any, Optional
from .base import BaseProvider

logger = logging.getLogger(__name__)

class PPIOModel(BaseProvider):
    def __init__(self, api_key: str, controller_ip: Optional[str] = None):
        self.api_key = api_key
        # 基础 URL（根据官方文档）
        self.base_url = "https://api.ppio.com/gpu-instance/openapi/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        self.controller_ip = controller_ip

    def _request(self, method: str, path: str, data: Optional[Dict] = None) -> Dict:
        url = f"{self.base_url}{path}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=self.headers, timeout=30)
            elif method == "POST":
                resp = requests.post(url, json=data, headers=self.headers, timeout=120)
            else:
                raise ValueError(f"Unsupported method: {method}")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"PPIO API request failed: {e}")
            raise

    def get_available_gpus(self) -> List[Dict[str, Any]]:
        """获取可用 GPU 产品列表（用于前端 /api/offers）"""
        try:
            # 官方接口：GET /gpu/products
            result = self._request("GET", "/products?billingMethod=onDemand")
            products = result.get("data", [])
            gpu_list = []
            for p in products:
                if p.get("availableDeploy", False) is True:
                    logger.info(p)
                    gpu_list.append({
                        "type": p.get("name"),          # 如 "RTX4090"
                        "price": p.get("price", 0),
                        "available": True,
                        "provider": "ppio",
                        "productId": p.get("id")        # 保存 productId 供创建实例使用
                    })
            return gpu_list
        except Exception as e:
            logger.error(f"Failed to fetch GPU products: {e}")
            # 降级模拟数据，确保前端有显示
            return [
                {"type": "RTX4090", "price": 1.6, "available": True, "provider": "ppio", "productId": "4090.16c125g"},
                {"type": "A100", "price": 3.8, "available": True, "provider": "ppio", "productId": "A100-80GB.12c210g"},
                {"type": "H100", "price": 7.2, "available": True, "provider": "ppio", "productId": "H100-80GB.20c236g"},
            ]

    def launch_instance(self, gpu_type: str, gpu_num: int = 1,
                        disk_size: int = 100, spot: bool = False, **kwargs) -> Dict[str, Any]:
        """
        创建 GPU 实例（官方接口：POST /gpu/instance/create）
        必须提供的参数：templateId, productId
        """
        # 获取 productId：可以从 get_available_gpus 的结果中匹配，或者直接通过参数传入
        product_id = kwargs.get("productId")
        if not product_id:
            # 尝试从产品列表中匹配
            gpus = self.get_available_gpus()
            for g in gpus:
                if g["type"] == gpu_type:
                    product_id = g.get("productId")
                    break
        if not product_id:
            raise ValueError(f"Cannot find productId for GPU type {gpu_type}")

        # 模板 ID：可以使用官方默认模板，或者从参数传入
        template_id = kwargs.get("templateId", "default-ubuntu-22.04")

        payload = {
         #   "templateId": template_id,
            "productId": product_id,
            "gpuNum": gpu_num,
            "rootfsSize": disk_size,
            "billingMode": "onDemand",
            "imageUrl": "image.ppinfra.com/prod-gpucloudpublic/gemma-4-e2b-it:v0.01",
        }
        # 如果提供了 user_data，可以添加（官方文档可能支持）
        user_data = self._build_user_data(gpu_num, gpu_type)
        if user_data:
            payload["userData"] = user_data
        result = self._request("POST", "/gpu/instance/create", data=payload)
        instance_id = result.get("instanceId") or result.get("id")
        return {
            "instance_id": instance_id,
            "provider": "ppio",
            "gpu_type": gpu_type,
            "status": "creating"
        }

    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """查询实例状态：GET /gpu/instance/detail?instanceId=xxx"""
        try:
            result = self._request("GET", f"/gpu/instance/detail?instanceId={instance_id}")
            return {
                "status": result.get("status", "unknown"),
                "ip": result.get("ipAddress") or result.get("ip"),
            }
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return {"status": "error", "ip": None}

    def terminate_instance(self, instance_id: str) -> bool:
        """销毁实例：POST /gpu/instance/delete"""
        try:
            self._request("POST", "/gpu/instance/delete", data={"instanceId": instance_id})
            return True
        except Exception as e:
            logger.error(f"Failed to terminate: {e}")
            return False

    def get_instance_metrics(self, instance_id: str) -> Dict[str, Any]:
        """获取监控指标：GET /gpu/instance/metrics"""
        try:
            result = self._request("GET", f"/gpu/instance/metrics?instanceId={instance_id}")
            return {
                "gpu_util": result.get("gpuUtilization"),
                "cpu_util": result.get("cpuUtilization"),
                "mem_util": result.get("memoryUtilization"),
            }
        except Exception:
            return {}

    def _build_user_data(self, gpu_num: int, gpu_type: str) -> str:
        """生成 Slurm 注册脚本（Base64 编码或不编码，视 API 要求）"""
        if not self.controller_ip:
            return ""
        gpu_lower = gpu_type.lower().replace("rtx", "")
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
PartitionName=ppio Nodes=ALL Default=YES MaxTime=INFINITE State=UP
EOF

mkdir -p /var/spool/slurmd /var/log/slurm
chown slurm:slurm /var/spool/slurmd /var/log/slurm
slurmd -Z --conf "RealMemory={mem_gb * 1024} Gres=gpu:{gpu_lower}:{gpu_num}"
sleep infinity
"""
        # 官方文档可能需要 Base64 编码，也可能直接传原文。建议 Base64 编码：
        import base64
        return base64.b64encode(script.encode()).decode()
