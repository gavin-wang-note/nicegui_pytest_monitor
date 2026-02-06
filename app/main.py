from nicegui import ui, app
from app.authentication import auth
from app.dashboards import SystemMonitor, TestMonitor
from app.services import monitor_service, storage_service
from config.settings import settings
import logging
import os
import time
import sqlite3
from datetime import datetime
from typing import Dict, Any

class RemoteTestMonitorApp:
    def __init__(self):
        self.system_monitor = SystemMonitor()
        self.test_monitor = TestMonitor()
        self.log_dir = settings.LOG_PATH
        os.makedirs(self.log_dir, exist_ok=True)
        
        self._setup_logging()
        self._setup_exception_handler()
    
    def _setup_logging(self):
        """设置日志记录"""
        log_file = os.path.join(self.log_dir, f"app_{datetime.now().strftime('%Y%m%d')}.log")
        
        logging.basicConfig(
            level=logging.DEBUG,
            format=settings.LOG_FORMAT,
            datefmt=settings.LOG_DATE_FORMAT,
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
            ]
        )
        
        self.logger = logging.getLogger('RemoteTestMonitor')
        self.logger.info("应用日志系统已启动")
    
    def _setup_exception_handler(self):
        """设置全局异常处理，防止NiceGUI并发问题导致应用崩溃"""
        def handle_exception(e: Exception):
            try:
                self.logger.error(f"捕获到异常: {type(e).__name__}: {str(e)}")
            except Exception:
                pass
        
        app.on_exception(handle_exception)
    
    def _create_log_panel(self):
        """创建日志面板"""
        with ui.card().classes('w-full p-4'):
            ui.label('系统日志').classes('text-2xl font-bold mb-4 text-gray-700')
            
            # 日志控制区 - 现代化样式
            with ui.card().classes('mb-4 bg-blue-50 border border-blue-100 rounded-lg'):
                with ui.row().classes('items-center justify-between p-4 flex-wrap gap-4'):
                    # 左侧：自动刷新开关
                    with ui.row().classes('items-center'):
                        self.auto_refresh = ui.switch('自动刷新', value=False)
                    
                    # 中间：日志级别筛选
                    with ui.row().classes('items-center'):
                        ui.label('级别:').classes('text-sm text-gray-600 mr-2')
                        self.log_level = ui.select(
                            ['全部', 'DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                            value='全部',
                            on_change=self._refresh_logs
                        ).classes('w-24')
                    
                    # 右侧：刷新间隔设置（根据自动刷新开关显示/隐藏）
                    with ui.row().classes('items-center'):
                        ui.label('刷新:').classes('text-sm text-gray-600 mr-2')
                        with ui.row().classes('items-center') as self.refresh_slider_container:
                            self.refresh_interval = ui.slider(
                                min=1, max=30, value=2, step=1, 
                                on_change=self._on_interval_change,
                            ).props('color=blue').classes('w-32')
                            self.interval_label = ui.label('2秒').classes('text-sm text-blue-600 font-bold')
                    
                    # 监听自动刷新开关来控制滑块显示/隐藏
                    self.auto_refresh.on_value_change(self._toggle_refresh_slider)
                    
                    # 根据自动刷新的初始值设置滑块的可见性
                    self.refresh_slider_container.visible = self.auto_refresh.value
                    
                    # 按钮组
                    with ui.row().classes('items-center'):
                        ui.button('刷新日志', on_click=self._refresh_logs).props('color=primary').classes('mr-2')
                        ui.button('清空显示', on_click=self._clear_logs).props('color=negative')
            
            # 日志显示区域
            self.log_output = ui.log().classes('w-full h-96')
            
            # 日志信息显示
            with ui.row().classes('justify-between mt-2 text-sm text-gray-500'):
                self.log_info = ui.label('准备就绪')
                self.log_time = ui.label('')
            
            # 初始化日志内容
            self._refresh_logs()
            
            # 设置自动刷新定时器 - 确保只有一个定时器实例
            self.logger.debug(f"正在创建日志自动刷新定时器，间隔: {self.refresh_interval.value}秒，自动刷新开关状态: {self.auto_refresh.value}")
            
            # 移除旧的定时器
            if hasattr(self, 'log_timer') and self.log_timer:
                self.logger.debug(f"移除旧的日志自动刷新定时器")
                self.log_timer.cancel()
                
            # 创建新的定时器，始终运行，但只在开关开启时执行刷新操作
            self.log_timer = ui.timer(interval=self.refresh_interval.value, callback=self._auto_refresh_logs, active=True)
            self.logger.debug(f"新的日志自动刷新定时器已创建并启动")
    
    def _on_interval_change(self, e):
        """刷新间隔变化时的处理"""
        self.interval_label.text = f'{e.value}秒'
        if hasattr(self, 'log_timer') and self.log_timer:
            self.log_timer.interval = e.value

    def _toggle_refresh_slider(self, e):
        """控制刷新滑块的显示/隐藏"""
        visible = e.value
        self.refresh_slider_container.visible = visible
        
        # 定时器始终运行，由_auto_refresh_logs方法内部的条件判断控制是否执行刷新操作
        self.logger.debug(f"自动刷新状态切换为: {'开启' if visible else '关闭'}")
    
    def _auto_refresh_logs(self):
        """自动刷新日志"""
        try:
            if self.auto_refresh.value:
                self.logger.debug(f"执行日志自动刷新，当前时间: {datetime.now()}")
                self._refresh_logs()
        except Exception as e:
            self.logger.error(f"自动刷新日志失败: {str(e)}")
            self.log_output.push(f'自动刷新日志失败: {str(e)}')
    
    def _find_latest_log_file(self):
        """查找最近的日志文件"""
        try:
            if not os.path.exists(self.log_dir):
                return None
            
            log_files = [f for f in os.listdir(self.log_dir) if f.startswith('app_') and f.endswith('.log')]
            if not log_files:
                return None
            
            # 按文件名排序，获取最新的日志文件
            log_files.sort(reverse=True)
            return os.path.join(self.log_dir, log_files[0])
        except Exception as e:
            self.logger.error(f"查找日志文件失败: {str(e)}")
            return None
    
    def _refresh_logs(self):
        """刷新日志内容"""
        try:
            # 获取当前日志文件路径
            today = datetime.now().strftime('%Y%m%d')
            log_file = os.path.join(self.log_dir, f"app_{today}.log")
            
            # 检查今天的日志文件是否存在，如果不存在则查找最近的日志文件
            if not os.path.exists(log_file):
                log_file = self._find_latest_log_file()
                if not log_file:
                    self.log_output.push('日志文件不存在')
                    self.log_info.text = '日志文件不存在'
                    return
                else:
                    self.log_info.text = f'显示历史日志: {os.path.basename(log_file)}'
            
            # 读取日志内容 - 优化性能
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    # 检查文件大小，对于大文件只读取最后5000行
                    f.seek(0, 2)
                    file_size = f.tell()
                    
                    # 如果文件大于5MB，只读取最后5000行
                    if file_size > 5 * 1024 * 1024:
                        lines = []
                        buffer = ''
                        f.seek(max(0, file_size - 500000))  # 从文件末尾附近开始读取
                        
                        while True:
                            chunk = f.read(1024)
                            if not chunk:
                                break
                            buffer += chunk
                            
                            # 按行分割
                            if '\n' in buffer:
                                parts = buffer.split('\n')
                                lines.extend(parts[:-1])
                                buffer = parts[-1]
                        
                        if buffer:
                            lines.append(buffer)
                            
                        # 取最后5000行
                        log_content = '\n'.join(lines[-5000:])
                    else:
                        # 小文件直接读取全部
                        f.seek(0)
                        log_content = f.read()
            except Exception as e:
                self.logger.error(f"读取日志文件失败: {str(e)}")
                self.log_output.push(f'读取日志文件失败: {str(e)}')
                self.log_info.text = '读取日志失败'
                return
            
            # 根据级别筛选日志
            level_filter = self.log_level.value
            if level_filter != '全部':
                # 优化的日志级别筛选
                filtered_lines = []
                for line in log_content.split('\n'):
                    if line and level_filter in line:
                        filtered_lines.append(line)
                log_content = '\n'.join(filtered_lines)
            
            # 更新日志显示
            self.log_output.clear()
            self.log_output.push(log_content)
            
            # 更新日志信息
            log_lines = len([l for l in log_content.split('\n') if l.strip()])
            current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.log_info.text = f'显示 {log_lines} 行日志 - 自动刷新: {self.auto_refresh.value} 间隔: {self.refresh_interval.value}秒'
            self.log_time.text = f'最后更新: {current_time}'
            self.logger.debug(f"日志刷新完成，行: {log_lines}，时间: {current_time}")
            
        except Exception as e:
            self.logger.error(f"读取日志文件失败: {str(e)}")
            self.log_output.push(f'读取日志文件失败: {str(e)}')
            self.log_info.text = '读取日志失败'
    
    def _clear_logs(self):
        """清空日志显示"""
        self.log_output.clear()
        self.log_info.text = '日志显示已清空'
    
    def _create_export_panel(self):
        """创建导出面板"""
        with ui.card().classes('w-full p-4'):
            ui.label('数据导出').classes('text-2xl font-bold mb-4 text-gray-700')
            
            # 导出配置卡片
            with ui.card().classes('mb-4 bg-blue-50 border border-blue-100 rounded-lg'):
                with ui.column().classes('p-4'):
                    # 数据类型选择
                    with ui.row().classes('items-center mb-4'):
                        ui.label('数据类型:').classes('text-sm text-gray-600 mr-2 w-24')
                        self.export_data_type = ui.select(
                            ['系统监控数据', '测试运行记录', '测试日志', '机器配置'],
                            value='系统监控数据',
                            on_change=self._on_export_data_type_change
                        ).classes('flex-grow')
                    
                    # 时间范围选择 - 初始隐藏，根据数据类型显示
                    with ui.column().classes('mb-4') as self.time_range_container:
                        ui.label('时间范围:').classes('text-sm text-gray-600 mb-2')
                        today = datetime.now().date()
                        # 格式化日期为ISO字符串，因为NiceGUI的date组件可能需要字符串格式的日期
                        today_str = today.strftime('%Y-%m-%d')
                        with ui.row().classes('items-center'):
                            self.start_time = ui.date().classes('mr-2')
                            ui.label('至').classes('text-sm text-gray-600 mx-2')
                            self.end_time = ui.date(value=today_str).classes('mr-2')
                        
                        # 添加日期选择验证
                        def validate_date(e):
                            """验证日期选择"""
                            if e.sender.value:
                                # 确保选择的日期不超过今天
                                selected_date = datetime.strptime(e.sender.value, '%Y-%m-%d').date()
                                if selected_date > today:
                                    ui.notify('不能选择未来日期', type='warning')
                                    e.sender.value = today_str
                        
                        # 为两个日期选择器添加验证
                        self.start_time.on_value_change(validate_date)
                        self.end_time.on_value_change(validate_date)
                    
                    # 导出格式选择
                    with ui.row().classes('items-center mb-4'):
                        ui.label('导出格式:').classes('text-sm text-gray-600 mr-2 w-24')
                        self.export_format = ui.select(
                            ['CSV', 'JSON'],
                            value='CSV'
                        ).classes('flex-grow')
                    
                    # 导出按钮
                    with ui.row().classes('items-center justify-end'):
                        self.export_button = ui.button('执行导出', on_click=self._export_data).props('color=primary')
            
            # 导出状态和结果显示
            self.export_status = ui.label('').classes('text-sm text-gray-600 mb-4')
            self.export_result = ui.column().classes('w-full')
        
        # 初始化时间范围显示
        self._on_export_data_type_change()
    
    def _on_export_data_type_change(self, e=None):
        """导出数据类型变化时的处理"""
        # 只有系统监控数据、测试运行记录、测试日志需要时间范围
        show_time_range = self.export_data_type.value in ['系统监控数据', '测试运行记录', '测试日志']
        self.time_range_container.visible = show_time_range
    
    def _export_data(self):
        """执行数据导出"""
        try:
            data_type = self.export_data_type.value
            export_format = self.export_format.value
            
            # 准备导出参数
            export_params = {
                'data_type': data_type,
                'format': export_format
            }
            
            # 如果需要时间范围
            if self.time_range_container.visible:
                if not self.start_time.value:
                    ui.notify('请选择开始时间', type='warning')
                    return
                if not self.end_time.value:
                    ui.notify('请选择结束时间', type='warning')
                    return
                
                # 确保日期值是datetime.date类型
                start_date = self.start_time.value
                end_date = self.end_time.value
                
                if isinstance(start_date, str):
                    start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                if isinstance(end_date, str):
                    end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                start_time = datetime.combine(start_date, datetime.min.time())
                end_time = datetime.combine(end_date, datetime.max.time())
                export_params['start_time'] = start_time
                export_params['end_time'] = end_time
            
            # 更新状态
            self.export_status.text = f'正在导出 {data_type}...'
            self.export_status.classes(remove='text-red-500').classes('text-blue-500')
            
            # 执行导出
            file_path = self._perform_export(export_params)
            
            # 显示结果
            self.export_status.text = f'导出完成: {os.path.basename(file_path)}'
            self.export_status.classes(remove='text-blue-500').classes('text-green-500')
            
            # 提供下载链接
            self.export_result.clear()
            import urllib.parse
            with self.export_result:
                filename = os.path.basename(file_path)
                encoded_filename = urllib.parse.quote(filename)
                ui.link(f'下载 {filename}', f'/export/{encoded_filename}')
                ui.label(f'文件位置: {file_path}').classes('text-xs text-gray-500 mt-2')
            
            ui.notify(f'{data_type} 导出成功', type='success')
            
        except Exception as e:
            self.export_status.text = f'导出失败: {str(e)}'
            self.export_status.classes(remove='text-blue-500 text-green-500').classes('text-red-500')
            ui.notify(f'导出失败: {str(e)}', type='error')
    
    def _perform_export(self, params):
        """执行实际的导出操作"""
        import csv
        import json
        import tempfile
        import os
        from datetime import datetime
        
        data_type = params['data_type']
        export_format = params['format']
        
        # 准备导出目录
        export_dir = os.path.join(os.getcwd(), 'export')
        os.makedirs(export_dir, exist_ok=True)
        
        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f'{data_type}_{timestamp}.{export_format.lower()}'
        file_path = os.path.join(export_dir, filename)
        
        if data_type == '系统监控数据':
            # 导出系统监控数据
            start_time = params['start_time']
            end_time = params['end_time']
            data = storage_service.get_system_data(start_time, end_time)
            
            if export_format == 'CSV':
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # 写入表头
                    writer.writerow(['时间戳', 'CPU使用率(%)', '内存使用率(%)', '磁盘使用率(%)', '发送流量(KB)', '接收流量(KB)', '进程ID', '进程名称', '节点名称'])
                    # 写入数据
                    for item in data:
                        writer.writerow([
                            item.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                            item.cpu_percent,
                            item.memory_percent,
                            item.disk_percent,
                            item.network_sent / 1024,
                            item.network_recv / 1024,
                            item.process_id,
                            item.process_name,
                            item.node_name
                        ])
            else:  # JSON
                export_data = []
                for item in data:
                    export_data.append({
                        '时间戳': item.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                        'CPU使用率(%)': item.cpu_percent,
                        '内存使用率(%)': item.memory_percent,
                        '磁盘使用率(%)': item.disk_percent,
                        '发送流量(KB)': item.network_sent / 1024,
                        '接收流量(KB)': item.network_recv / 1024,
                        '进程ID': item.process_id,
                        '进程名称': item.process_name,
                        '节点名称': item.node_name
                    })
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        elif data_type == '测试运行记录':
            # 导出测试运行记录
            start_time = params['start_time']
            end_time = params['end_time']
            data = storage_service.get_test_runs_by_time_range(start_time, end_time)
            
            if export_format == 'CSV':
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # 写入表头
                    writer.writerow(['运行ID', '开始时间', '结束时间', '状态', '总测试数', '通过数', '失败数', '跳过数', '测试路径', '报告路径', '节点名称', '退出码', '执行类型'])
                    # 写入数据
                    for item in data:
                        writer.writerow([
                            item.run_id,
                            item.start_time.strftime('%Y-%m-%d %H:%M:%S'),
                            item.end_time.strftime('%Y-%m-%d %H:%M:%S') if item.end_time else '',
                            item.status,
                            item.total_tests,
                            item.passed_tests,
                            item.failed_tests,
                            item.skipped_tests,
                            item.test_path,
                            item.report_path or '',
                            item.node_name,
                            item.exit_code or '',
                            item.execution_type
                        ])
            else:  # JSON
                export_data = []
                for item in data:
                    export_data.append({
                        '运行ID': item.run_id,
                        '开始时间': item.start_time.strftime('%Y-%m-%d %H:%M:%S'),
                        '结束时间': item.end_time.strftime('%Y-%m-%d %H:%M:%S') if item.end_time else '',
                        '状态': item.status,
                        '总测试数': item.total_tests,
                        '通过数': item.passed_tests,
                        '失败数': item.failed_tests,
                        '跳过数': item.skipped_tests,
                        '测试路径': item.test_path,
                        '报告路径': item.report_path or '',
                        '节点名称': item.node_name,
                        '退出码': item.exit_code or '',
                        '执行类型': item.execution_type
                    })
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        elif data_type == '测试日志':
            # 这里需要获取所有测试日志，或者提供测试ID选择
            # 为简化实现，先导出最近的1000条日志
            with sqlite3.connect(settings.DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT run_id, timestamp, level, message FROM test_logs ORDER BY timestamp DESC LIMIT 1000')
                data = cursor.fetchall()
            
            if export_format == 'CSV':
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # 写入表头
                    writer.writerow(['运行ID', '时间戳', '日志级别', '消息'])
                    # 写入数据
                    for item in data:
                        writer.writerow([
                            item[0],
                            datetime.fromisoformat(item[1]).strftime('%Y-%m-%d %H:%M:%S'),
                            item[2],
                            item[3]
                        ])
            else:  # JSON
                export_data = []
                for item in data:
                    export_data.append({
                        '运行ID': item[0],
                        '时间戳': datetime.fromisoformat(item[1]).strftime('%Y-%m-%d %H:%M:%S'),
                        '日志级别': item[2],
                        '消息': item[3]
                    })
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        elif data_type == '机器配置':
            # 导出机器配置
            from app.services import remote_machine_service
            data = remote_machine_service.get_all_machines()
            
            if export_format == 'CSV':
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    # 写入表头
                    writer.writerow(['机器ID', '名称', '主机', '端口', '平台', '用户名', '状态', '描述'])
                    # 写入数据
                    for item in data:
                        writer.writerow([
                            item.machine_id,
                            item.name,
                            item.host,
                            item.port,
                            'Linux' if item.platform == 'linux' else 'Windows',
                            item.username,
                            item.status,
                            item.description or ''
                        ])
            else:  # JSON
                export_data = []
                for item in data:
                    export_data.append({
                        '机器ID': item.machine_id,
                        '名称': item.name,
                        '主机': item.host,
                        '端口': item.port,
                        '平台': 'Linux' if item.platform == 'linux' else 'Windows',
                        '用户名': item.username,
                        '状态': item.status,
                        '描述': item.description or ''
                    })
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
        
        return file_path
    
    def run(self):
        """运行应用"""
        # 启动系统监控服务
        monitor_service.start_monitoring()
        
        # 定义报告文件访问路由
        @ui.page('/report/{run_id}')
        def report_page(run_id: str):
            """报告查看页面"""
            # 获取测试运行信息
            test_run = storage_service.get_test_run(run_id)
            if not test_run or not test_run.report_path:
                ui.label('报告不存在').classes('text-red-500 text-xl')
                return
            
            # 检查报告文件是否存在
            report_path = test_run.report_path
            if not os.path.exists(report_path):
                ui.label('报告文件不存在').classes('text-red-500 text-xl')
                return
            
            # 设置页面标题
            ui.page_title = f'测试报告 - {run_id}'
            
            # 读取报告文件内容
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report_content = f.read()
                
                # 显示报告内容 (使用add_body_html处理包含script标签的HTML)
                ui.add_body_html(report_content)
                
            except Exception as e:
                ui.label(f'读取报告失败: {str(e)}').classes('text-red-500 text-xl')
        
        # 定义导出文件下载路由
        @ui.page('/export/{filename}')
        def export_download_page(filename: str):
            """导出文件下载页面"""
            import fastapi
            import urllib.parse
            
            # 先对URL编码的文件名进行解码，得到原始文件名
            decoded_filename = urllib.parse.unquote(filename)
            
            # 构建导出文件的完整路径
            export_dir = os.path.join(os.getcwd(), 'export')
            file_path = os.path.join(export_dir, decoded_filename)
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                return ui.label('文件不存在').classes('text-red-500 text-xl')
            
            try:
                # 使用FastAPI的Response直接返回文件内容，完全控制响应头
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                # 构建符合RFC 5987标准的Content-Disposition头
                encoded_filename = urllib.parse.quote(decoded_filename)
                # 使用filename*=charset''encoded-filename格式，两个单引号是必须的分隔符
                content_disposition = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
                
                return fastapi.Response(
                    content=content,
                    media_type='application/octet-stream',
                    headers={
                        'Content-Disposition': content_disposition,
                        'Content-Length': str(len(content))
                    }
                )
            except Exception as e:
                return ui.label(f'下载失败: {str(e)}').classes('text-red-500 text-xl')
        
        # 定义页面路由
        @ui.page('/')
        def index_page():
            """应用首页"""
            if auth.is_authenticated():
                # 已认证，显示主界面
                app.page_title = settings.APP_NAME
                
                with ui.header(elevated=True).classes('items-center justify-between'):
                    ui.label(settings.APP_NAME).classes('text-xl font-bold')
                    ui.button('登出', on_click=self._handle_logout)
                
                # 通知区域 - 使用模态对话框
                self.notification_area = None
                
                # 创建通知模态区域 - 修复黄色背景导致的文字清晰度问题
                with ui.dialog() as self.notification_dialog:
                    with ui.card().classes('p-6 bg-white border border-gray-300 rounded-lg shadow-lg'):
                        self.notification_text = ui.label('').classes('text-gray-800 text-base leading-relaxed mb-4')
                        with ui.row().classes('w-full justify-end mt-4'):
                            ui.button('确定', on_click=self._close_notification).props('flat color=primary')
                
                def show_notification(message, timeout=3.0):
                    """显示通知"""
                    self.notification_text.text = message
                    self.notification_dialog.open()
                    
                    # 自动关闭
                    if timeout > 0:
                        ui.timer(interval=timeout, callback=self._close_notification, once=True)
                
                # 保存通知函数
                ui.show_notification = show_notification
                
                with ui.footer().classes('text-center text-gray-500 text-sm'):
                    ui.label(f'{settings.APP_NAME} v{settings.APP_VERSION}')
                
                with ui.page_sticky(position='bottom-right', x_offset=20, y_offset=20):
                    ui.button(on_click=lambda: self._show_welcome_message(), icon='info')
                
                # 主内容区域
                with ui.row().classes('w-full items-center mb-2'):
                    ui.label('📊').classes('text-2xl')
                    ui.label('远程测试监控系统').classes('text-xl font-bold text-gray-800')
                
                with ui.tabs().classes('w-full') as tabs:
                    system_tab = ui.tab('🖥️ 系统监控').classes('text-base font-medium')
                    test_tab = ui.tab('🧪 测试监控').classes('text-base font-medium')
                    log_tab = ui.tab('📋 日志').classes('text-base font-medium')
                    export_tab = ui.tab('📊 导出').classes('text-base font-medium')
                
                with ui.tab_panels(tabs, value=system_tab).classes('w-full'):
                    # 系统监控面板
                    with ui.tab_panel(system_tab):
                        self.system_monitor.create_dashboard()
                    
                    # 测试监控面板
                    with ui.tab_panel(test_tab):
                        self.test_monitor.create_dashboard()
                    
                    # 日志面板
                    with ui.tab_panel(log_tab):
                        self._create_log_panel()
                    
                    # 导出面板
                    with ui.tab_panel(export_tab):
                        self._create_export_panel()
            else:
                # 未认证，显示登录界面
                self._show_login_page()
        
        # 运行 NiceGUI 应用
        ui.run(
            title=settings.APP_NAME,
            host=settings.HOST,
            port=settings.PORT,
            show=False
        )
    
    def _show_login_page(self):
        """显示登录页面"""
        
        with ui.card().classes('w-96 mx-auto mt-20'):
            ui.label('远程测试监控系统').classes('text-xl font-bold mb-4 text-center')
            
            username_input = ui.input(label='用户名').classes('mb-2')
            password_input = ui.input(label='密码', password=True).classes('mb-4')
            
            error_label = ui.label('').classes('text-red-500 mb-2')
            
            def handle_login():
                self.logger.info(f"尝试登录，用户名: {username_input.value}")
                if auth.login(username_input.value, password_input.value):
                    # 登录成功，刷新页面
                    self.logger.info(f"用户 {username_input.value} 登录成功")
                    ui.notify('登录成功！')
                    ui.navigate.to('/')
                else:
                    error_label.text = '用户名或密码错误'
                    self.logger.warning(f"用户 {username_input.value} 登录失败")
            
            ui.button('登录', on_click=handle_login).classes('w-full')
    
    def _close_notification(self):
        """关闭通知"""
        self.notification_dialog.close()
    
    def _show_welcome_message(self):
        """显示欢迎消息"""
        ui.show_notification('欢迎使用远程测试监控系统！', 3.0)
    
    def _handle_logout(self):
        """处理用户登出"""
        username = auth.get_username()
        auth.logout()
        ui.notify('已成功登出')
        if username:
            self.logger.info(f"用户 {username} 登出成功")
        else:
            self.logger.info("用户登出成功")
        ui.navigate.to('/login')

# 创建应用实例
app_instance = RemoteTestMonitorApp()

# 运行应用（如果直接执行该文件）
if __name__ in {"__main__", "__mp_main__"}:
    app_instance.run()
