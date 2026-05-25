cd /home/ubuntu/gpu-platform
source venv/bin/activate

# 设置环境变量
#export AUTODL_API_TOKEN="your_autodl_token_here"
#export PPIO_API_KEY="your_ppio_api_key_here"
#export SLURM_CONTROLLER_IP="10.0.0.8"  # 控制节点实际 IP

# 启动服务
nohup python app.py &

