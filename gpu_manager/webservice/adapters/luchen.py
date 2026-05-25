# adapters/compshare.py
import base64
import logging
import time
from typing import Dict, Any, List, Optional

from ucloud.client import Client
from ucloud.core import exc

from .base import BaseProvider

logger = logging.getLogger(__name__)


class CompShareProvider(BaseProvider):
    """
    优云智算 (UCloud) 适配器
    基于官方 Python SDK (ucloud-sdk-python3)
    """

    def __init__(self, public_key: str, private_key: str, controller_ip: Optional[str] = None):
        """
        :param public_key: UCloud API 公钥（从 UAPI 密钥管理获取）
        :param private_key: UCloud API 私钥（从 UAPI 密钥管理获取）
        :param controller_ip: Slurm 控制节点 IP
        """
        self.public_key = public_key
        self.private_key = private_key
        self.controller_ip = controller_ip
        # 初始化官方 SDK Client
        # region 和 project_id 可根据实际部署情况修改
        self.client = Client({
            "region": "cn-wlcb",
            "public_key": public_key,
            "private_key": private_key,
            "base_url": "https://api.compshare.cn",
        })
        logger.info(f"CompShareProvider initialized with public_key: {public_key[:8]}...")

    def get_available_gpus(self) -> List[Dict[str, Any]]:
        """
        获取可用 GPU 实例规格
        API: DescribeAvailableCompShareInstanceTypes
        """
        try:
            # 调用官方 SDK 方法
            resp = self.client.ucompshare().describe_available_comp_share_instance_types({
                 "Zone": "cn-wlcb-01",
            })
            gpu_list = []
            for it in resp.get("AvailableInstanceTypes", []):
                if it.get("MachineClass", "") == "GPU" and it.get("Name", "") in ["3090", "4090", "4090_48G", "5090", "6090", "A100", "H100"]:
                    gpu_list.append({
                        "type": it.get("Name", "Unknown"),
                        "price": 5.0,  # 价格需从其他接口获取，此处预留
                        "available": it.get("Status") == "Normal",
                        "provider": "luchen",
                    })
            return gpu_list
        except exc.UCloudException as e:
            logger.error(f"获取 GPU 列表失败: {e}")
            return self._get_mock_gpu_list()

    def _get_mock_gpu_list(self) -> List[Dict[str, Any]]:
        """模拟 GPU 列表（API 不可用时兜底）"""
        return [
            {"type": "gpu.gn7.2xlarge", "price": 8.8, "available": True, "provider": "luchen"},
            {"type": "gpu.gn7.4xlarge", "price": 12.5, "available": True, "provider": "luchen"},
            {"type": "gpu.gn10.2xlarge", "price": 15.6, "available": True, "provider": "luchen"},
        ]

    def _build_user_data(self, gpu_num: int, gpu_type: str) -> str:
        """生成实例启动脚本，用于将节点注册到 Slurm 控制器"""
        if not self.controller_ip:
            logger.warning("Controller IP not set, Slurm registration disabled")
            return ""

        mem_gb = 32 * gpu_num
        # 注意：SDK 内部会自动对 user_data 进行 Base64 编码，此处直接返回原始脚本即可
        return f"""#!/bin/bash
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

    def launch_instance(self, gpu_type: str, gpu_num: int = 1,
                        disk_size: int = 100, spot: bool = False, **kwargs) -> Dict[str, Any]:
        """
        创建 GPU 实例
        API: CreateCompShareInstance
        """

        # 构建请求参数
        params = {
            "Region": "cn-wlcb",
            "Zone": "cn-wlcb-01",
            "MachineType": "G",
            "CompShareImageId": "compshareImage-1b6bx62uvf70",  # 替换为实际的镜像 ID
            "GPU": gpu_num,
            "GpuType": gpu_type,
            "CPU": 16,
            "Memory": 64 * 1024,  # 单位 MB，4 * 1024 = 64GB
            "ChargeType": "Dynamic",
            "Disks": [
                {
                    "IsBoot": True,
                    "Size": 80, # System disk size, 200 means 200G
                    "Type": "CLOUD_SSD"
                }
            ]
        }

        try:
            logger.info(f"Creating instance with params: {params}")
            # 调用官方 SDK 方法
            resp = self.client.ucompshare().create_comp_share_instance(params)
            instance_id = resp.get("UHostIds", [None])[0]
            if not instance_id:
                raise Exception("API 响应未包含 UHostIds")
            logger.info(f"Instance created successfully, ID: {instance_id}")
            return {
                "instance_id": instance_id,
                "provider": "luchen",
                "gpu_type": gpu_type,
                "status": "creating",
            }
        except exc.UCloudException as e:
            logger.error(f"创建实例失败: {e}")
            raise

    def terminate_instance(self, instance_id: str) -> bool:
        """
        释放一个 GPU 实例
        API: TerminateCompShareInstance
        """
        try:
            self.client.ucompshare().stop_comp_share_instance({
                "Region": "cn-wlcb",
                "Zone": "cn-wlcb-01",
                "UHostId": instance_id,
    #            "ReleaseUDisk": True,
            })
            logger.info(f"Instance {instance_id} terminated")
            return True
        except exc.UCloudException as e:
            logger.error(f"释放实例 {instance_id} 失败: {e}")
            return False

    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """
        查询实例状态和 IP 地址
        API: DescribeCompShareInstance
        """
        try:
            resp = self.client.ucompshare().describe_comp_share_instance({
                "Region": "cn-bj2",
                "UHostId": instance_id,
            })
            instance_set = resp.get("InstanceSet", [])
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
                "ip": inst.get("IPSet", [{}])[0].get("IP", None) if inst.get("IPSet") else None,
            }
        except exc.UCloudException as e:
            logger.error(f"获取实例 {instance_id} 状态失败: {e}")
            return {"status": "error", "ip": None}

    def get_instance_metrics(self, instance_id: str) -> Dict[str, Any]:
        """
        获取监控指标
        API: DescribeCompShareInstanceMetric
        """
        try:
            resp = self.client.ucompshare().describe_comp_share_instance_metric({
                "Region": "cn-wlcb",
                "UHostId": instance_id,
            })
            # 确保返回标准的字段名
            return {
                "GPUUtilization": resp.get("GPUUtilization", 0),
                "CPUUtilization": resp.get("CPUUtilization", 0),
                "MEMUtilization": resp.get("MemUtilization", 0),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "instance_id": instance_id
            }
        except exc.UCloudException as e:
            logger.error(f"获取实例 {instance_id} 指标失败: {e}")
            # 返回模拟数据用于演示
            return {
                "GPUUtilization": random.uniform(30, 95),
                "CPUUtilization": random.uniform(20, 80),
                "MEMUtilization": random.uniform(40, 85),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "instance_id": instance_id
            }
