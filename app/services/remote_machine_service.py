import uuid
import logging
import asyncio
import subprocess
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List
from app.models import RemoteMachine, MachineStatus
from app.services.storage_service import storage_service

def _setup_logger():
    logger = logging.getLogger('RemoteTestMonitor.RemoteMachineService')
    logger.setLevel(logging.DEBUG)
    return logger

logger = _setup_logger()

class RemoteMachineService:
    def __init__(self):
        self._active_connections: Dict[str, Any] = {}
        self._connection_lock = threading.Lock()
    
    def test_connection(self, machine: RemoteMachine) -> tuple[bool, str]:
        """测试机器连接"""
        try:
            logger.info(f"[TEST CONN] 机器: {machine.name}, 平台: {machine.platform}, 主机: {machine.host}, 端口: {machine.port}")
            
            if machine.platform == "linux":
                return self._test_ssh_connection(machine)
            elif machine.platform == "windows":
                return self._test_winrm_connection(machine)
            else:
                return False, f"不支持的平台: {machine.platform}"
        except Exception as e:
            logger.error(f"测试连接失败: {str(e)}")
            return False, f"连接测试失败: {str(e)}"
    
    def _test_ssh_connection(self, machine: RemoteMachine) -> tuple[bool, str]:
        """测试SSH连接（Linux）"""
        try:
            import paramiko
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                'hostname': machine.host,
                'port': machine.port,
                'username': machine.username,
                'timeout': 10
            }
            
            if machine.private_key_path:
                try:
                    key = paramiko.RSAKey.from_private_key_file(machine.private_key_path)
                    connect_kwargs['pkey'] = key
                except Exception as e:
                    return False, f"加载私钥失败: {str(e)}"
            elif machine.password:
                connect_kwargs['password'] = machine.password
            
            ssh.connect(**connect_kwargs)
            
            stdin, stdout, stderr = ssh.exec_command('echo "connection test successful"', timeout=10)
            result = stdout.read().decode().strip()
            
            ssh.close()
            
            if result == "connection test successful":
                return True, "SSH连接成功"
            else:
                return False, f"SSH连接异常: {result}"
                
        except ImportError:
            logger.warning("paramiko未安装，尝试使用ssh命令测试")
            return self._test_ssh_by_command(machine)
        except Exception as e:
            logger.error(f"SSH连接测试失败: {str(e)}")
            return False, f"SSH连接失败: {str(e)}"
    
    def _test_ssh_by_command(self, machine: RemoteMachine) -> tuple[bool, str]:
        """通过ssh命令测试连接（备选方案）"""
        try:
            if machine.password:
                return False, "需要安装paramiko库来支持SSH连接: pip install paramiko"
            else:
                return False, "需要安装paramiko库来支持SSH连接: pip install paramiko"
        except Exception as e:
            return False, f"SSH连接测试失败: {str(e)}"
    
    def _test_winrm_connection(self, machine: RemoteMachine) -> tuple[bool, str]:
        """测试WinRM连接（Windows）"""
        try:
            import winrm
            from config.settings import settings
            
            url = f'http://{machine.host}:{machine.port}/wsman'
            logger.info(f"[WINRM DEBUG] ====================")
            logger.info(f"[WINRM DEBUG] 目标机器: {machine.name}")
            logger.info(f"[WINRM DEBUG] 平台: {machine.platform}")
            logger.info(f"[WINRM DEBUG] 主机: {machine.host}")
            logger.info(f"[WINRM DEBUG] 端口: {machine.port}")
            logger.info(f"[WINRM DEBUG] 完整URL: {url}")
            logger.info(f"[WINRM DEBUG] 用户名: {machine.username}")
            logger.info(f"[WINRM DEBUG] 配置的WinRM端口: {settings.WINRM_HTTP_PORT}, {settings.WINRM_HTTPS_PORT}")
            
            # 检查端口是否为WinRM端口
            is_valid_port = machine.port in [settings.WINRM_HTTP_PORT, settings.WINRM_HTTPS_PORT]
            if not is_valid_port:
                logger.error(f"[WINRM DEBUG] ⚠️ 端口错误! WinRM应该使用 {settings.WINRM_HTTP_PORT} 或 {settings.WINRM_HTTPS_PORT}，当前使用: {machine.port}")
                logger.error(f"[WINRM DEBUG] 这可能导致连接失败!")
            
            logger.info(f"[WINRM DEBUG] 开始创建winrm Session...")
            
            session = winrm.Session(
                url,
                auth=(machine.username, machine.password or ''),
                transport='ntlm',
                server_cert_validation='ignore'
            )
            
            logger.info(f"[WINRM DEBUG] 执行测试命令: echo connection_test_successful")
            result = session.run_cmd('echo', ['connection_test_successful'])
            logger.info(f"[WINRM DEBUG] 命令执行结果 - status_code: {result.status_code}")
            
            if result.status_code == 0:
                logger.info(f"WinRM连接成功: {machine.name}")
                return True, "WinRM连接成功"
            else:
                error_msg = result.std_err.decode('gbk', errors='replace') or result.std_out.decode('gbk', errors='replace')
                logger.warning(f"WinRM命令执行异常: {error_msg}")
                return False, f"WinRM连接异常: {error_msg}"
                
        except ImportError:
            logger.warning("pywinrm未安装")
            return False, "需要安装pywinrm库来支持Windows远程连接: pip install pywinrm"
        except Exception as e:
            error_msg = str(e)
            logger.error(f"WinRM连接测试失败: {error_msg}")
            
            # 检查是否是端口问题导致的SSH服务检测
            if 'BadStatusLine' in error_msg or 'SSH-' in error_msg:
                return False, f"检测到SSH服务而非WinRM服务\nWindows远程管理有两种方式:\n1. WinRM (推荐): 端口 {settings.WINRM_HTTP_PORT}(HTTP) 或 {settings.WINRM_HTTPS_PORT}(HTTPS)\n2. SSH: 端口 {settings.SSH_PORT} (需选择'Linux'平台)\n\n问题原因分析:\n- 当前使用的端口: {machine.port} (非WinRM端口)\n- 建议使用端口: {settings.WINRM_HTTP_PORT} (WinRM HTTP)\n\n请确认Windows主机已启用WinRM:\npowershell: Enable-PSRemoting -Force"
            
            if '401' in error_msg or 'Unauthorized' in error_msg or 'credentials' in error_msg.lower():
                return False, f"""认证失败 (401 Unauthorized)
可能原因:
1. 用户名或密码错误
2. 本地账户需要额外配置
3. Windows安全策略限制

解决方法:
1. 检查用户名密码是否正确
2. 尝试使用Administrator账户
3. 或在Windows上运行:
   winrm set winrm/config/service '@{{AllowUnencrypted="true"}}'
   winrm set winrm/config/service/auth '@{{Basic="true"}}'"""
            
            return False, f"WinRM连接失败: {error_msg}"
    
    def execute_command(self, machine: RemoteMachine, command: str, timeout: int = 300) -> tuple[bool, str, str]:
        """在远程机器上执行命令"""
        try:
            if machine.platform == "linux":
                return self._execute_ssh(machine, command, timeout)
            elif machine.platform == "windows":
                return self._execute_winrm(machine, command, timeout)
            else:
                return False, "", f"不支持的平台: {machine.platform}"
        except Exception as e:
            logger.error(f"远程执行失败: {str(e)}")
            return False, "", f"执行失败: {str(e)}"
    
    def _execute_ssh(self, machine: RemoteMachine, command: str, timeout: int) -> tuple[bool, str, str]:
        """通过SSH执行命令"""
        try:
            import paramiko
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                'hostname': machine.host,
                'port': machine.port,
                'username': machine.username,
                'timeout': 30
            }
            
            if machine.private_key_path:
                key = paramiko.RSAKey.from_private_key_file(machine.private_key_path)
                connect_kwargs['pkey'] = key
            elif machine.password:
                connect_kwargs['password'] = machine.password
            
            ssh.connect(**connect_kwargs)
            
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            stdout_content = stdout.read().decode('utf-8', errors='replace')
            stderr_content = stderr.read().decode('utf-8', errors='replace')
            exit_code = stdout.channel.recv_exit_status()
            
            ssh.close()
            
            return exit_code == 0, stdout_content, stderr_content
            
        except ImportError:
            return False, "", "需要安装paramiko库: pip install paramiko"
        except Exception as e:
            return False, "", f"SSH执行失败: {str(e)}"
    
    def _execute_winrm(self, machine: RemoteMachine, command: str, timeout: int) -> tuple[bool, str, str]:
        """通过WinRM执行命令"""
        try:
            import winrm
            
            session = winrm.Session(
                f'http://{machine.host}:{machine.port}/wsman',
                auth=(machine.username, machine.password or ''),
                transport='ntlm',
                server_cert_validation='ignore'
            )
            
            result = session.run_cmd('cmd.exe', ['/c', command])
            
            return result.status_code == 0, result.std_out.decode('utf-8', errors='replace'), result.std_err.decode('utf-8', errors='replace')
            
        except ImportError:
            return False, "", "需要安装pywinrm库: pip install pywinrm"
        except Exception as e:
            return False, "", f"WinRM执行失败: {str(e)}"
    
    def _format_path_for_platform(self, path: str, platform: str) -> str:
        """根据目标平台格式化路径"""
        if not path:
            return path
            
        if platform == "windows":
            # 处理Windows路径格式
            # 1. 替换正斜杠为反斜杠
            formatted = path.replace('/', '\\')
            # 2. 处理UNC路径（保留格式）
            if formatted.startswith('\\\\'):
                return formatted
            # 3. 处理驱动器号格式（确保大小写一致）
            if len(formatted) >= 2 and formatted[1] == ':':
                formatted = formatted[0].upper() + formatted[1:]
            return formatted
        elif platform == "linux":
            # 处理Linux路径格式
            # 1. 替换反斜杠为正斜杠
            formatted = path.replace('\\', '/')
            # 2. 确保路径以/开头（绝对路径）
            if not formatted.startswith('/'):
                logger.warning(f"Linux路径应该是绝对路径，当前路径: {path}")
            return formatted
        else:
            return path
    
    def check_remote_path_exists(self, machine: RemoteMachine, path: str) -> tuple[bool, str]:
        """检查远程路径是否存在"""
        try:
            logger.debug(f"[路径检查] 开始检查远程路径，机器: {machine.name}, 平台: {machine.platform}, 原始路径: {path}")
            
            if machine.platform == "linux":
                formatted_path = self._format_path_for_platform(path, "linux")
                logger.debug(f"[路径检查] Linux平台，格式化后路径: {formatted_path}")
                return self._check_linux_path_exists(machine, formatted_path)
            elif machine.platform == "windows":
                formatted_path = self._format_path_for_platform(path, "windows")
                logger.debug(f"[路径检查] Windows平台，格式化后路径: {formatted_path}")
                return self._check_windows_path_exists(machine, formatted_path)
            else:
                logger.error(f"[路径检查] 不支持的平台: {machine.platform}")
                return False, f"不支持的平台: {machine.platform}"
        except Exception as e:
            logger.error(f"检查远程路径失败: {str(e)}")
            return False, f"检查失败: {str(e)}"
    
    def _check_linux_path_exists(self, machine: RemoteMachine, path: str) -> tuple[bool, str]:
        """检查Linux远程路径是否存在"""
        import paramiko
        import shlex
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connect_kwargs = {
            'hostname': machine.host,
            'port': machine.port,
            'username': machine.username,
            'timeout': 30
        }
        
        if machine.private_key_path:
            key = paramiko.RSAKey.from_private_key_file(machine.private_key_path)
            connect_kwargs['pkey'] = key
        elif machine.password:
            connect_kwargs['password'] = machine.password
        
        ssh.connect(**connect_kwargs)
        
        # 使用更安全的方式检查路径是否存在，通过转义路径避免特殊字符问题
        escaped_path = shlex.quote(path)
        command = f'if [ -e {escaped_path} ]; then echo "exists"; else echo "not exists"; fi'
        
        logger.debug(f"[Linux路径检查] 执行命令: {command}")
        stdin, stdout, stderr = ssh.exec_command(command, timeout=30)
        
        output = stdout.read().decode('utf-8').strip()
        error = stderr.read().decode('utf-8').strip()
        
        ssh.close()
        
        logger.debug(f"[Linux路径检查] 命令输出: {output}")
        if error:
            logger.debug(f"[Linux路径检查] 命令错误: {error}")
            # 提供更友好的错误信息
            if len(error) > 100:
                return False, "检查失败: 路径不存在或权限不足"
            return False, f"检查失败: {error}"
        
        return output == "exists", ""
    
    def _check_windows_path_exists(self, machine: RemoteMachine, path: str) -> tuple[bool, str]:
        """检查Windows远程路径是否存在"""
        import winrm
        import xml.etree.ElementTree as ET
        
        session = winrm.Session(
            f'http://{machine.host}:{machine.port}/wsman',
            auth=(machine.username, machine.password or ''),
            transport='ntlm',
            server_cert_validation='ignore'
        )
        
        # 转义单引号
        escaped_path = path.replace("'", "''")
        
        # 使用PowerShell检查路径是否存在，使用-LiteralPath参数处理特殊字符
        check_script = f"""$path = '{escaped_path}'
if (Test-Path -LiteralPath $path) {{
    Write-Output "exists"
}} else {{
    Write-Output "not exists"
}}
"""
        
        logger.debug(f"[Windows路径检查] 格式化路径: {path}")
        logger.debug(f"[Windows路径检查] 转义后路径: {escaped_path}")
        logger.debug(f"[Windows路径检查] 执行PowerShell脚本: {check_script}")
        
        result = session.run_ps(check_script)
        output = result.std_out.decode('utf-8', errors='replace').strip()
        error = result.std_err.decode('utf-8', errors='replace').strip()
        
        logger.debug(f"[Windows路径检查] 命令输出: {output}")
        if error:
            logger.debug(f"[Windows路径检查] 命令错误: {error}")
            # 尝试解析CLIXML格式的错误信息
            if error.strip().startswith('#< CLIXML'):
                try:
                    # 提取XML部分
                    xml_start = error.find('<Objs')
                    if xml_start != -1:
                        xml_content = error[xml_start:]
                        root = ET.fromstring(xml_content)
                        
                        # 只有当找到真正的错误元素时才视为错误
                        error_elements = root.findall('.//S[@S="Error"]')
                        if error_elements:
                            error_msg = error_elements[-1].text
                            if error_msg:
                                return False, f"检查失败: {error_msg}"
                        
                        # 如果没有找到错误元素，忽略CLIXML输出
                        logger.debug(f"[Windows路径检查] CLIXML包含非错误信息，忽略")
                except Exception as e:
                    logger.debug(f"解析CLIXML错误失败: {str(e)}")
            else:
                # 非CLIXML错误，返回失败
                if len(error) > 100:
                    return False, "检查失败: 路径不存在或权限不足"
                return False, f"检查失败: {error}"
        
        return output == "exists", ""
    
    def execute_test(self, machine: RemoteMachine, test_path: str, run_id: str) -> bool:
        """在远程机器上执行测试"""
        try:
            # 首先检查测试路径是否存在
            exists, error_msg = self.check_remote_path_exists(machine, test_path)
            if not exists:
                logger.error(f"远程测试路径不存在: {test_path}, {error_msg}")
                # 记录错误日志
                from app.models import TestLog, TestRun
                from app.services.storage_service import storage_service
                from datetime import datetime
                
                # 更新测试运行状态为失败
                test_run = storage_service.get_test_run(run_id)
                if test_run:
                    test_run.status = "failed"
                    test_run.end_time = datetime.now()
                    storage_service.save_test_run(test_run)
                    
                # 保存错误日志
                error_message = f"测试失败: 远程路径不存在: {test_path}"
                if error_msg:
                    error_message += f" ({error_msg})"
                    
                test_log = TestLog(
                    run_id=run_id,
                    timestamp=datetime.now(),
                    level="ERROR",
                    message=error_message
                )
                storage_service.save_test_log(test_log)
                
                # 触发状态回调
                from app.services.test_service import test_service
                if test_run:
                    test_service._trigger_status_callbacks(test_run)
                    
                return False
            
            if machine.platform == "linux":
                return self._execute_test_linux(machine, test_path, run_id)
            elif machine.platform == "windows":
                return self._execute_test_windows(machine, test_path, run_id)
            else:
                logger.error(f"不支持的平台: {machine.platform}")
                return False
        except Exception as e:
            logger.error(f"远程测试执行失败: {str(e)}")
            return False
    
    def _execute_test_linux(self, machine: RemoteMachine, test_path: str, run_id: str) -> bool:
        """在Linux机器上执行测试并流式输出日志"""
        try:
            import paramiko
            from app.services.test_service import test_service
            from app.models import TestLog
            from datetime import datetime
            
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            connect_kwargs = {
                'hostname': machine.host,
                'port': machine.port,
                'username': machine.username,
                'timeout': 30
            }
            
            if machine.private_key_path:
                key = paramiko.RSAKey.from_private_key_file(machine.private_key_path)
                connect_kwargs['pkey'] = key
            elif machine.password:
                connect_kwargs['password'] = machine.password
            
            ssh.connect(**connect_kwargs)
            
            remote_report_path = f"/tmp/{run_id}_report.html"
            command = f'cd /tmp && python -m pytest {test_path} -v --tb=short --html={remote_report_path} --self-contained-html 2>&1'
            
            stdin, stdout, stderr = ssh.exec_command(command, timeout=600)
            
            # 实时读取输出
            while not stdout.channel.exit_status_ready():
                if stdout.channel.recv_ready():
                    line = stdout.channel.recv(1024).decode('utf-8', errors='replace')
                    for l in line.strip().splitlines():
                        if l:
                            # 保存日志到数据库
                            test_log = TestLog(
                                run_id=run_id,
                                timestamp=datetime.now(),
                                level="INFO",
                                message=l
                            )
                            from app.services.storage_service import storage_service
                            storage_service.save_test_log(test_log)
                            
                            # 触发日志回调
                            test_service._trigger_log_callbacks(test_log)
                            
                            # 解析测试结果行，更新统计计数
                            test_service._parse_test_result_line(l, run_id)
                            
                            # 解析测试统计信息
                            test_service._parse_test_statistics(l, run_id)
                            
                            logger.debug(f"[Remote][{run_id}] Linux测试输出: {l[:50]}...")
                
                if stderr.channel.recv_ready():
                    line = stderr.channel.recv(1024).decode('utf-8', errors='replace')
                    for l in line.strip().splitlines():
                        if l:
                            # 保存错误日志到数据库
                            test_log = TestLog(
                                run_id=run_id,
                                timestamp=datetime.now(),
                                level="ERROR",
                                message=l
                            )
                            from app.services.storage_service import storage_service
                            storage_service.save_test_log(test_log)
                            
                            # 触发日志回调
                            test_service._trigger_log_callbacks(test_log)
                            logger.warning(f"[Remote][{run_id}] Linux测试错误: {l[:50]}...")
                
                # 防止CPU过度占用
                import time
                time.sleep(0.1)
            
            # 读取剩余输出
            while stdout.channel.recv_ready():
                line = stdout.channel.recv(1024).decode('utf-8', errors='replace')
                for l in line.strip().splitlines():
                    if l:
                        test_log = TestLog(
                            run_id=run_id,
                            timestamp=datetime.now(),
                            level="INFO",
                            message=l
                        )
                        from app.services.storage_service import storage_service
                        storage_service.save_test_log(test_log)
                        test_service._trigger_log_callbacks(test_log)
                        
                        # 解析测试结果行，更新统计计数
                        test_service._parse_test_result_line(l, run_id)
                        
                        # 解析测试统计信息
                        test_service._parse_test_statistics(l, run_id)
                        
                        logger.debug(f"[Remote][{run_id}] Linux测试输出: {l[:50]}...")
            
            while stderr.channel.recv_ready():
                line = stderr.channel.recv(1024).decode('utf-8', errors='replace')
                for l in line.strip().splitlines():
                    if l:
                        test_log = TestLog(
                            run_id=run_id,
                            timestamp=datetime.now(),
                            level="ERROR",
                            message=l
                        )
                        from app.services.storage_service import storage_service
                        storage_service.save_test_log(test_log)
                        test_service._trigger_log_callbacks(test_log)
                        logger.warning(f"[Remote][{run_id}] Linux测试错误: {l[:50]}...")
            
            exit_code = stdout.channel.recv_exit_status()
            logger.info(f"[Remote][{run_id}] Linux测试执行完成，退出码: {exit_code}")
            
            # 传输报告文件到本地
            from config.settings import settings
            import os
            
            # 确保本地报告目录存在
            os.makedirs(settings.TEST_REPORTS_PATH, exist_ok=True)
            
            # 本地报告路径
            local_report_path = os.path.join(settings.TEST_REPORTS_PATH, f"{run_id}_report.html")
            
            try:
                # 使用 SCP 传输报告文件
                from paramiko import SFTPClient
                
                with ssh.open_sftp() as sftp:
                    # 检查远程报告文件是否存在
                    try:
                        sftp.stat(remote_report_path)
                        sftp.get(remote_report_path, local_report_path)
                        logger.info(f"[Remote][{run_id}] 报告文件已从 {remote_report_path} 传输到 {local_report_path}")
                        
                        # 更新测试运行记录的报告路径
                        from app.services.storage_service import storage_service
                        from app.models import TestRun
                        
                        test_run = storage_service.get_test_run(run_id)
                        if test_run:
                            test_run.report_path = local_report_path
                            test_run.status = "completed" if exit_code == 0 else "failed"
                            storage_service.save_test_run(test_run)
                            logger.info(f"[Remote][{run_id}] 测试运行记录已更新，报告路径: {local_report_path}")
                            
                            # 触发状态更新回调
                            from app.services.test_service import test_service
                            test_service._trigger_status_callbacks(test_run)
                    except IOError:
                        logger.warning(f"[Remote][{run_id}] 远程报告文件 {remote_report_path} 不存在")
            except Exception as e:
                logger.error(f"[Remote][{run_id}] 传输报告文件失败: {str(e)}")
            
            # 无论报告传输是否成功，都更新测试运行状态
            from app.services.storage_service import storage_service
            from app.models import TestRun
            test_run = storage_service.get_test_run(run_id)
            if test_run:
                test_run.status = "completed" if exit_code == 0 else "failed"
                storage_service.save_test_run(test_run)
                from app.services.test_service import test_service
                test_service._trigger_status_callbacks(test_run)
                logger.info(f"[Remote][{run_id}] 测试运行状态已更新: {test_run.status}")
            
            ssh.close()
            
            return exit_code == 0
            
        except Exception as e:
            logger.error(f"Linux远程测试执行失败: {str(e)}")
            # 记录错误日志
            from app.models import TestLog
            from datetime import datetime
            test_log = TestLog(
                run_id=run_id,
                timestamp=datetime.now(),
                level="ERROR",
                message=f"测试执行失败: {str(e)}"
            )
            from app.services.storage_service import storage_service
            storage_service.save_test_log(test_log)
            from app.services.test_service import test_service
            test_service._trigger_log_callbacks(test_log)
            
            # 更新测试运行状态为失败
            from app.models import TestRun
            test_run = storage_service.get_test_run(run_id)
            if test_run:
                test_run.status = "failed"
                storage_service.save_test_run(test_run)
                test_service._trigger_status_callbacks(test_run)
                logger.info(f"[Remote][{run_id}] 测试运行状态已更新为失败")
            
            return False
    
    def _execute_test_windows(self, machine: RemoteMachine, test_path: str, run_id: str) -> bool:
        """在Windows机器上执行测试并流式输出日志"""
        try:
            import winrm
            from app.services.test_service import test_service
            from app.models import TestLog
            from datetime import datetime
            import time
            
            session = winrm.Session(
                f'http://{machine.host}:{machine.port}/wsman',
                auth=(machine.username, machine.password or ''),
                transport='ntlm',
                server_cert_validation='ignore'
            )
            
            # 命令行使用%TEMP%语法
            cmd_remote_report_path = fr"%TEMP%\{run_id}_report.html"
            command = f'cd /d %TEMP% && python -m pytest {test_path} -v --tb=short --html={cmd_remote_report_path} --self-contained-html' 
            # PowerShell使用$env:TEMP语法
            powershell_remote_path = fr"$env:TEMP\{run_id}_report.html"
            
            # 使用winrm的run_cmd方法并实时读取输出
            result = session.run_cmd('cmd.exe', ['/c', f'{command} 2>&1'])
            
            # 处理stdout输出
            stdout = result.std_out.decode('gbk', errors='replace')
            for line in stdout.splitlines():
                if line.strip():
                    # 保存日志到数据库
                    test_log = TestLog(
                        run_id=run_id,
                        timestamp=datetime.now(),
                        level="INFO",
                        message=line.strip()
                    )
                    from app.services.storage_service import storage_service
                    storage_service.save_test_log(test_log)
                    
                    # 触发日志回调
                    test_service._trigger_log_callbacks(test_log)
                    
                    # 解析测试结果行，更新统计计数
                    test_service._parse_test_result_line(line.strip(), run_id)
                    
                    # 解析测试统计信息
                    test_service._parse_test_statistics(line.strip(), run_id)
                    logger.debug(f"[Remote][{run_id}] Windows测试输出: {line.strip()[:50]}...")
                    
                    # 防止CPU过度占用
                    time.sleep(0.1)
            
            # 处理stderr输出
            stderr = result.std_err.decode('gbk', errors='replace')
            if stderr:
                for line in stderr.splitlines():
                    if line.strip():
                        # 保存错误日志到数据库
                        test_log = TestLog(
                            run_id=run_id,
                            timestamp=datetime.now(),
                            level="ERROR",
                            message=line.strip()
                        )
                        from app.services.storage_service import storage_service
                        storage_service.save_test_log(test_log)
                        
                        # 触发日志回调
                        test_service._trigger_log_callbacks(test_log)
                        logger.warning(f"[Remote][{run_id}] Windows测试错误: {line.strip()[:50]}...")
                        
                        # 防止CPU过度占用
                        time.sleep(0.1)
            
            logger.info(f"[Remote][{run_id}] Windows测试执行完成，退出码: {result.status_code}")
            
            # 传输报告文件到本地
            from config.settings import settings
            import os
            
            # 确保本地报告目录存在
            os.makedirs(settings.TEST_REPORTS_PATH, exist_ok=True)
            
            # 本地报告路径
            local_report_path = os.path.join(settings.TEST_REPORTS_PATH, f"{run_id}_report.html")
            
            try:
                # 首先检查远程报告文件是否存在
                check_script = f"""$remotePath = "{powershell_remote_path}"
if (Test-Path -LiteralPath $remotePath) {{
    Write-Output "Found"
}} else {{
    Write-Output "Not found"
}}"""
                
                check_result = session.run_ps(check_script)
                check_output = check_result.std_out.decode('utf-8', errors='replace').strip()
                
                if check_output == "Found":
                    # 如果远程报告文件存在，获取其内容
                    get_content_script = f"""$remotePath = "{powershell_remote_path}"
Get-Content $remotePath -Raw"""
                    
                    content_result = session.run_ps(get_content_script)
                    report_content = content_result.std_out.decode('utf-8', errors='replace')
                    
                    # 将内容保存到本地文件
                    with open(local_report_path, 'w', encoding='utf-8') as f:
                        f.write(report_content)
                    
                    logger.info(f"[Remote][{run_id}] 报告文件已从 {powershell_remote_path} 传输到 {local_report_path}")
                    
                    # 更新测试运行记录的报告路径
                    from app.services.storage_service import storage_service
                    from app.models import TestRun
                    
                    test_run = storage_service.get_test_run(run_id)
                    if test_run:
                        test_run.report_path = local_report_path
                        test_run.status = "completed" if result.status_code == 0 else "failed"
                        storage_service.save_test_run(test_run)
                        logger.info(f"[Remote][{run_id}] 测试运行记录已更新，报告路径: {local_report_path}")
                        
                        # 触发状态更新回调
                        from app.services.test_service import test_service
                        test_service._trigger_status_callbacks(test_run)
                else:
                    logger.warning(f"[Remote][{run_id}] 远程报告文件 {powershell_remote_path} 不存在")
            except Exception as e:
                logger.error(f"[Remote][{run_id}] 传输报告文件失败: {str(e)}")
            
            # 无论报告传输是否成功，都更新测试运行状态
            from app.services.storage_service import storage_service
            from app.models import TestRun
            test_run = storage_service.get_test_run(run_id)
            if test_run:
                test_run.status = "completed" if result.status_code == 0 else "failed"
                storage_service.save_test_run(test_run)
                from app.services.test_service import test_service
                test_service._trigger_status_callbacks(test_run)
                logger.info(f"[Remote][{run_id}] 测试运行状态已更新: {test_run.status}")
            
            return True
            
        except Exception as e:
            logger.error(f"Windows远程测试执行失败: {str(e)}")
            # 记录错误日志
            from app.models import TestLog
            from datetime import datetime
            test_log = TestLog(
                run_id=run_id,
                timestamp=datetime.now(),
                level="ERROR",
                message=f"测试执行失败: {str(e)}"
            )
            from app.services.storage_service import storage_service
            storage_service.save_test_log(test_log)
            from app.services.test_service import test_service
            test_service._trigger_log_callbacks(test_log)
            
            # 更新测试运行状态为失败
            from app.models import TestRun
            test_run = storage_service.get_test_run(run_id)
            if test_run:
                test_run.status = "failed"
                storage_service.save_test_run(test_run)
                test_service._trigger_status_callbacks(test_run)
                logger.info(f"[Remote][{run_id}] 测试运行状态已更新为失败")
                
            return False
    
    def add_machine(self, name: str, host: str, port: int, platform: str, username: str, password: str = None, private_key_path: str = None, description: str = None) -> tuple[bool, str]:
        """添加新机器"""
        try:
            if not self.validate_host(host):
                return False, "主机IP格式不正确"
            
            if not self.validate_port(port):
                return False, "端口号必须在1-65535之间"
            
            if self.check_duplicate(host, port, username):
                return False, "该机器配置已存在（相同主机、端口和用户名）"
            
            machine_id = str(uuid.uuid4())
            now = datetime.now().isoformat()
            
            machine = RemoteMachine(
                machine_id=machine_id,
                name=name,
                host=host,
                port=port,
                platform=platform,
                username=username,
                password=password,
                private_key_path=private_key_path,
                description=description,
                status=MachineStatus.UNKNOWN.value,
                created_at=now,
                updated_at=None
            )
            
            if storage_service.save_remote_machine(machine):
                logger.info(f"已添加机器: {name} ({host})")
                return True, f"机器 '{name}' 添加成功"
            else:
                return False, "保存机器配置失败"
                
        except Exception as e:
            logger.error(f"添加机器失败: {str(e)}")
            return False, f"添加失败: {str(e)}"
    
    def update_machine(self, machine_id: str, name: str = None, host: str = None, port: int = None, platform: str = None, username: str = None, password: str = None, description: str = None) -> tuple[bool, str]:
        """更新机器配置"""
        try:
            machine = storage_service.get_remote_machine(machine_id)
            if not machine:
                return False, "机器不存在"
            
            if name:
                machine.name = name
            if host:
                if not self.validate_host(host):
                    return False, "主机IP格式不正确"
                machine.host = host
            if port:
                if not self.validate_port(port):
                    return False, "端口号必须在1-65535之间"
                machine.port = port
            if platform:
                machine.platform = platform
            if username:
                machine.username = username
            if password:
                machine.password = password
            if description is not None:
                machine.description = description
            
            machine.updated_at = datetime.now().isoformat()
            
            if storage_service.save_remote_machine(machine):
                logger.info(f"已更新机器: {machine.name}")
                return True, f"机器 '{machine.name}' 更新成功"
            else:
                return False, "保存机器配置失败"
                
        except Exception as e:
            logger.error(f"更新机器失败: {str(e)}")
            return False, f"更新失败: {str(e)}"
    
    def update_machine_status(self, machine_id: str, status: str):
        """更新机器状态"""
        try:
            machine = storage_service.get_remote_machine(machine_id)
            if machine:
                machine.status = status
                machine.updated_at = datetime.now().isoformat()
                storage_service.save_remote_machine(machine)
                logger.info(f"已更新机器状态: {machine.name} -> {status}")
        except Exception as e:
            logger.error(f"更新机器状态失败: {str(e)}")
    
    def validate_host(self, host: str) -> bool:
        """验证主机IP格式"""
        try:
            import ipaddress
            ipaddress.ip_address(host)
            return True
        except ValueError:
            # 尝试作为域名验证
            import re
            if re.match(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$', host):
                return True
            return False
    
    def validate_port(self, port: int) -> bool:
        """验证端口号"""
        return 1 <= port <= 65535
    
    def check_duplicate(self, host: str, port: int, username: str) -> bool:
        """检查机器是否已存在"""
        return storage_service.check_machine_exists(host, port, username)
    
    def delete_machine(self, machine_id: str) -> tuple[bool, str]:
        """删除机器"""
        try:
            machine = storage_service.get_remote_machine(machine_id)
            if not machine:
                return False, "机器不存在"
            
            if storage_service.delete_remote_machine(machine_id):
                logger.info(f"已删除机器: {machine.name}")
                return True, f"机器 '{machine.name}' 已删除"
            else:
                return False, "删除机器失败"
                
        except Exception as e:
            logger.error(f"删除机器失败: {str(e)}")
            return False, f"删除失败: {str(e)}"
    
    def get_all_machines(self) -> List[RemoteMachine]:
        """获取所有机器"""
        return storage_service.get_all_remote_machines()
    
    def get_machine(self, machine_id: str) -> Optional[RemoteMachine]:
        """获取指定机器"""
        return storage_service.get_remote_machine(machine_id)
    
    def check_machine_online(self, machine: RemoteMachine) -> bool:
        """检查机器是否在线"""
        success, _ = self.test_connection(machine)
        return success

remote_machine_service = RemoteMachineService()
