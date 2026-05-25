# adapters/base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class BaseProvider(ABC):
    """云厂商适配器基类"""
    
    @abstractmethod
    def get_available_gpus(self) -> List[Dict[str, Any]]:
        """获取可用 GPU 列表和价格"""
        pass
    
    @abstractmethod
    def launch_instance(self, gpu_type: str, gpu_num: int = 1,
                        disk_size: int = 100, **kwargs) -> Dict[str, Any]:
        """创建 GPU 实例"""
        pass
    
    @abstractmethod
    def terminate_instance(self, instance_id: str) -> bool:
        """终止实例"""
        pass
    
    @abstractmethod
    def get_instance_status(self, instance_id: str) -> Dict[str, Any]:
        """获取实例状态"""
        pass
    
    @abstractmethod
    def get_instance_metrics(self, instance_id: str) -> Dict[str, Any]:
        """获取监控指标"""
        pass
