cd ~/gpu-platform
python -m venv venv && source venv/bin/activate

# 安装依赖包
pip install flask flask-cors requests sqlalchemy apscheduler \
    paramiko python-dateutil
pip install --upgrade ucloud-sdk-python3 
pip install paramiko
pip install PyJWT bcrypt
pip install -r ~/gpu-platform/requirements.txt
