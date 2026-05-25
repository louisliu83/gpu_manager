# 安装 Slurm 组件
sudo apt install -y slurm-wlm slurmdbd munge

# 生成 Munge 密钥（用于节点间认证）
sudo /usr/sbin/create-munge-key
sudo systemctl enable munge
sudo systemctl start munge

# 初始化 Slurm 数据库
sudo mysql
