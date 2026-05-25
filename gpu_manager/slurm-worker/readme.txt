1. 制作自定义镜像；
功能点：（1）预装基础环境，安装pytorch相关软件
        （2）性能测试脚本
        （3）外网可达测试脚本
        （4）其它

2. 推送镜像到算力厂商仓库；
docker push

3. 拉起镜像，安装pytorch相关软件，执行benchmark测试脚本；
docker pull
