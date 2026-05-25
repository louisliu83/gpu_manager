import os

# Slurm 配置
SLURM_CONTROLLER_IP = os.environ.get("SLURM_CONTROLLER_IP", "124.221.53.205")
SLURM_USER = os.environ.get("SLURM_USER", "slurm")

# 数据库
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///gpu_platform.db")

# AutoDL 配置
AUTODL_API_TOKEN = 
AUTODL_API_BASE = "https://private.autodl.com"

# 派欧云配置
PPIO_API_KEY = 
PPIO_API_BASE = "https://api.ppio.com/gpu-instance/openapi/v1"

# Ucloud配置
DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
LUCHEN_ACCESS_KEY = 
LUCHEN_SECRET_KEY = 
