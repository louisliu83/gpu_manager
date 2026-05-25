# adapters/benchmark.py
import subprocess
import paramiko
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class GPUValidator:
    """GPU性能测试工具"""
    
    @staticmethod
    def run_cuda_benchmark(ssh_client) -> Dict[str, Any]:
        """运行CUDA性能测试"""
        results = {}
        
        try:
            # 1. GPU基本信息
            stdin, stdout, stderr = ssh_client.exec_command(
                "nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader 2>/dev/null || echo 'No GPU'"
            )
            gpu_info = stdout.read().decode().strip()
            results['gpu_info'] = gpu_info.split(', ') if gpu_info and gpu_info != 'No GPU' else ['No NVIDIA GPU detected']
            
            # 2. 当前GPU状态
            stdin, stdout, stderr = ssh_client.exec_command(
                "nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader 2>/dev/null || echo 'N/A'"
            )
            current_stats = stdout.read().decode().strip()
            results['current_stats'] = current_stats
            
            # 3. 运行Python性能测试
            python_test_script = '''
python3 << 'EOF'
import sys
import time
import subprocess

def test_numpy_performance():
    """使用numpy进行性能测试（无需cupy）"""
    try:
        import numpy as np
        results = {}
        
        # NumPy矩阵乘法测试（CPU，但可作为参考）
        sizes = [1024, 2048, 3072]
        for size in sizes:
            a = np.random.randn(size, size).astype(np.float32)
            b = np.random.randn(size, size).astype(np.float32)
            start = time.time()
            c = np.dot(a, b)
            elapsed = time.time() - start
            gflops = (2.0 * size ** 3) / (elapsed * 1e9)
            results[f'numpy_matmul_{size}'] = {
                'time_ms': elapsed * 1000,
                'gflops': round(gflops, 2),
                'note': 'CPU-based (NumPy)'
            }
        return results
    except ImportError:
        return {'error': 'numpy not installed'}

def test_cupy_performance():
    """使用cupy进行GPU性能测试"""
    try:
        import cupy as cp
        results = {}
        
        # 矩阵乘法测试
        sizes = [1024, 2048, 4096]
        for size in sizes:
            a = cp.random.randn(size, size).astype(cp.float32)
            b = cp.random.randn(size, size).astype(cp.float32)
            cp.cuda.Stream.null.synchronize()
            start = time.time()
            c = cp.dot(a, b)
            cp.cuda.Stream.null.synchronize()
            elapsed = time.time() - start
            gflops = (2.0 * size ** 3) / (elapsed * 1e9)
            results[f'cuda_matmul_{size}'] = {
                'time_ms': elapsed * 1000,
                'gflops': round(gflops, 2)
            }
        
        # 内存带宽测试
        size_mb = 1024
        data = cp.random.randn(size_mb * 1024 * 1024 // 8)
        cp.cuda.Stream.null.synchronize()
        start = time.time()
        cp.copy(data, data)
        cp.cuda.Stream.null.synchronize()
        elapsed = time.time() - start
        bandwidth = (2 * size_mb) / elapsed
        results['memory_bandwidth_gb_s'] = round(bandwidth, 2)
        
        # GPU显存信息
        free_mem, total_mem = cp.cuda.runtime.memGetInfo()
        results['gpu_memory'] = {
            'total_gb': round(total_mem / 1024**3, 2),
            'free_gb': round(free_mem / 1024**3, 2)
        }
        
        return results
    except ImportError:
        return {'error': 'cupy not installed, try: pip install cupy-cuda12x'}
    except Exception as e:
        return {'error': str(e)}

if __name__ == '__main__':
    # 尝试GPU测试
    gpu_results = test_cupy_performance()
    if 'error' in gpu_results:
        # 回退到NumPy测试
        gpu_results = test_numpy_performance()
    
    import json
    print(json.dumps(gpu_results))
EOF
'''
            
            stdin, stdout, stderr = ssh_client.exec_command(python_test_script, timeout=60)
            output = stdout.read().decode()
            error = stderr.read().decode()
            
            if output.strip():
                try:
                    import json as json_lib
                    results['benchmark'] = json_lib.loads(output.strip())
                except:
                    results['benchmark'] = {'output': output.strip(), 'error': error if error else None}
            else:
                results['benchmark'] = {'error': error or 'No output from test script'}
                
        except Exception as e:
            logger.error(f"Benchmark execution failed: {e}")
            results['error'] = str(e)
        
        return results
    
    @staticmethod
    def run_simple_benchmark(ssh_client) -> Dict[str, Any]:
        """运行简单的CPU/内存性能测试（当GPU测试不可用时）"""
        results = {}
        
        try:
            # CPU信息
            stdin, stdout, stderr = ssh_client.exec_command("nproc && cat /proc/cpuinfo | grep 'model name' | head -1")
            cpu_info = stdout.read().decode()
            results['cpu_info'] = cpu_info.strip()
            
            # 内存信息
            stdin, stdout, stderr = ssh_client.exec_command("free -h")
            mem_info = stdout.read().decode()
            results['memory_info'] = mem_info.strip()
            
            # 磁盘性能
            stdin, stdout, stderr = ssh_client.exec_command("dd if=/dev/zero of=/tmp/test bs=1M count=100 2>&1 | grep copied || echo 'Disk test failed'")
            disk_test = stdout.read().decode()
            results['disk_test'] = disk_test.strip()
            
            # 系统负载
            stdin, stdout, stderr = ssh_client.exec_command("uptime")
            uptime = stdout.read().decode()
            results['uptime'] = uptime.strip()
            
        except Exception as e:
            logger.error(f"Simple benchmark failed: {e}")
            results['error'] = str(e)
        
        return results


class BenchmarkRunner:
    """性能测试运行器"""
    
    def __init__(self, ssh_key_path: str = None, ssh_user: str = 'root'):
        self.ssh_key_path = ssh_key_path
        self.ssh_user = ssh_user
    
    def run_benchmark(self, ip_address: str, instance_id: str = None) -> Dict[str, Any]:
        """通过SSH连接到实例并运行性能测试"""
        results = {
            'instance_id': instance_id,
            'timestamp': None,
            'tests': {}
        }
        
        try:
            import datetime
            results['timestamp'] = datetime.datetime.now().isoformat()
            
            # 创建SSH客户端
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # 尝试连接
            connected = False
            for user in ['root', 'ubuntu', 'admin', 'ec2-user']:
                try:
                    ssh.connect(ip_address, username=user, timeout=15)
                    connected = True
                    logger.info(f"Connected to {ip_address} as {user}")
                    break
                except paramiko.AuthenticationException:
                    continue
                except Exception as e:
                    logger.debug(f"Failed to connect as {user}: {e}")
                    continue
            
            if not connected:
                raise Exception("Unable to authenticate to instance with common usernames")
            
            # 检查是否有NVIDIA驱动
            stdin, stdout, stderr = ssh.exec_command("which nvidia-smi 2>/dev/null")
            has_nvidia = bool(stdout.read().decode().strip())
            
            if has_nvidia:
                results['tests']['gpu'] = GPUValidator.run_cuda_benchmark(ssh)
            else:
                results['tests']['system'] = GPUValidator.run_simple_benchmark(ssh)
            
            # 获取系统信息
            stdin, stdout, stderr = ssh.exec_command("uname -a")
            results['system_info'] = stdout.read().decode().strip()
            
            ssh.close()
            
        except Exception as e:
            logger.error(f"Benchmark connection failed: {e}")
            results['error'] = str(e)
        
        return results
