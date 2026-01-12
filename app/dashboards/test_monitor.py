import os
import webbrowser

from nicegui import ui, app
from typing import List, Dict, Any
from datetime import datetime
from app.models import TestLog, TestRun
from app.services import test_service, storage_service


class TestMonitor:
    def __init__(self):
        self.current_run_id = None
        self.test_logs = []
        self.max_log_lines = 500  # 最大日志行数
    
    def create_dashboard(self):
        """创建测试监控仪表板"""
        with ui.card().classes('w-full'):
            ui.label('测试监控').classes('text-xl font-bold mb-4')
            
            # 测试执行控制
            with ui.row().classes('w-full mb-4'):
                self.test_path_input = ui.input(
                    label='测试路径',
                    placeholder='例如: ./tests 或 tests/test_example.py'
                ).classes('flex-grow mr-2')
                
                self.start_button = ui.button('开始测试', on_click=self._start_test).classes('mr-2')
                self.stop_button = ui.button('停止测试', on_click=self._stop_test)
                self.stop_button.disable()
            
            # 测试状态显示
            with ui.card().classes('w-full mb-4'):
                self.test_status = ui.label('等待测试执行').classes('text-lg')
            
            # 测试日志显示
            with ui.card().classes('w-full'):
                ui.label('测试日志').classes('text-lg font-semibold mb-2')
                
                # 日志输出区域
                self.log_output = ui.log().classes('w-full h-96')
                
                # 日志控制按钮
                with ui.row().classes('mt-2'):
                    ui.button('清空日志', on_click=lambda: self.log_output.clear())
                    ui.button('下载日志', on_click=self._download_logs).classes('ml-2')
            
            # 测试报告区域
            with ui.card().classes('w-full mt-4'):
                with ui.row().classes('w-full justify-between items-center mb-2'):
                    ui.label('测试报告').classes('text-lg font-semibold')
                    self.refresh_button = ui.button('刷新', on_click=self._load_reports, icon='refresh').props('flat')
                
                self.report_list = ui.list().classes('w-full')
                self._load_reports()
        
        # 注册测试日志回调
        test_service.register_log_callback(self._update_log)
        test_service.register_status_callback(self._update_test_status)
    
    def _start_test(self):
        """开始执行测试"""
        test_path = self.test_path_input.value.strip()
        if not test_path:
            ui.notify('请输入测试路径', type='warning')
            return
        
        try:
            # 开始测试
            self.current_run_id = test_service.start_test(test_path)
            
            # 更新UI状态
            self.start_button.disable()
            self.stop_button.enable()
            self.test_status.text = f'测试正在执行... (Run ID: {self.current_run_id})'
            self.test_status.classes(remove='text-red-500 text-green-500').classes('text-blue-500')
            
            ui.notify(f'测试已开始: {test_path}', type='success')
        except Exception as e:
            ui.notify(f'测试启动失败: {str(e)}', type='error')
    
    def _stop_test(self):
        """停止正在执行的测试"""
        if self.current_run_id:
            if test_service.stop_test(self.current_run_id):
                # 更新UI状态
                self.start_button.enable()
                self.stop_button.disable()
                self.test_status.text = f'测试已停止 (Run ID: {self.current_run_id})'
                self.test_status.classes(remove='text-blue-500 text-green-500').classes('text-red-500')
                ui.notify('测试已停止', type='info')
                self.current_run_id = None
            else:
                ui.notify('停止测试失败', type='error')
    
    def _update_log(self, test_log: TestLog):
        """更新测试日志"""
        # 只显示当前测试的日志
        if not self.current_run_id or test_log.run_id != self.current_run_id:
            return
        
        # 添加日志到输出
        self.log_output.push(f"[{test_log.timestamp.strftime('%H:%M:%S')}] {test_log.message}")
        
        # 限制日志行数
        if len(self.log_output.lines) > self.max_log_lines:
            self.log_output.lines = self.log_output.lines[-self.max_log_lines:]
    
    def _update_test_status(self, test_run: TestRun):
        """更新测试状态"""
        if not self.current_run_id or test_run.run_id != self.current_run_id:
            return
        
        # 更新状态显示
        if test_run.status == 'completed':
            self.test_status.text = f'测试已完成 (Run ID: {test_run.run_id})'
            self.test_status.classes(remove='text-blue-500 text-red-500').classes('text-green-500')
            ui.notify('测试已完成', type='success')
        elif test_run.status == 'failed':
            self.test_status.text = f'测试失败 (Run ID: {test_run.run_id})'
            self.test_status.classes(remove='text-blue-500 text-green-500').classes('text-red-500')
            ui.notify('测试失败', type='error')
        elif test_run.status == 'stopped':
            self.test_status.text = f'测试已停止 (Run ID: {test_run.run_id})'
            self.test_status.classes(remove='text-blue-500 text-green-500').classes('text-red-500')
        
        # 更新按钮状态
        self.start_button.enable()
        self.stop_button.disable()
        
        # 清空当前运行ID
        self.current_run_id = None
        
        # 重新加载测试报告列表
        self._load_reports()
    
    def _download_logs(self):
        """下载测试日志"""
        if not self.current_run_id:
            ui.notify('没有正在执行的测试', type='warning')
            return
        
        # 获取日志数据
        logs = storage_service.get_test_logs(self.current_run_id)
        if not logs:
            ui.notify('没有日志数据', type='warning')
            return
        
        # 生成日志内容
        log_content = '\n'.join([
            f"[{log.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {log.message}"
            for log in logs
        ])
        
        # 创建下载链接
        ui.download(
            content=log_content,
            filename=f'test_logs_{self.current_run_id}.txt',
            mime_type='text/plain'
        )
    
    def _load_reports(self):
        """加载测试报告列表"""
        # 清空现有报告列表
        self.report_list.clear()
        
        # 从数据库获取所有测试运行记录
        test_runs = storage_service.get_all_test_runs()
        
        # 格式化数据为前端需要的格式
        reports = []
        for run in test_runs:
            # 计算运行时间（如果存在结束时间）
            duration = None
            if run.end_time:
                duration = (run.end_time - run.start_time).total_seconds()
            
            # 格式化状态显示
            status_display = self._get_status_display(run.status)
            
            # 格式化开始时间
            start_time_str = run.start_time.strftime('%Y-%m-%d %H:%M:%S')
            
            # 添加到报告列表
            reports.append({
                'run_id': run.run_id,
                'test_path': run.test_path,
                'status': run.status,
                'status_display': status_display,
                'start_time': start_time_str,
                'duration': duration,
                'total_tests': run.total_tests,
                'passed_tests': run.passed_tests,
                'failed_tests': run.failed_tests,
                'skipped_tests': run.skipped_tests,
                'report_path': run.report_path
            })
        
        # 如果没有报告数据，显示空状态
        if not reports:
            with self.report_list:
                with ui.card().classes('w-full bg-gray-50'):
                    with ui.column().classes('w-full items-center p-4'):
                        ui.icon('article', size='48px', color='gray')
                        ui.label('暂无测试报告').classes('text-lg mt-2 text-gray-600')
                        ui.label('执行测试后将在这里显示报告').classes('text-sm text-gray-400')
        else:
            # 添加报告到列表，使用现代化样式
            for report in reports:
                with self.report_list:
                    with ui.card().classes('w-full mb-4 border rounded-lg shadow-sm hover:shadow-md transition-all duration-200'):
                        with ui.column().classes('p-3 w-full'):
                            # 标题行
                            with ui.row().classes('justify-between items-center w-full mb-2'):
                                ui.label(f"测试: {report['test_path']}").classes('font-semibold text-lg')
                                status_color = self._get_status_color(report['status'])
                                ui.badge(report['status_display'], color=status_color)
                            
                            # 详情行 - 网格布局
                            with ui.grid(columns=3).classes('w-full gap-2 text-sm text-gray-500'):
                                ui.label(f"开始时间: {report['start_time']}").classes('col-span-1')
                                ui.label(f"Run ID: {report['run_id']}").classes('col-span-1')
                                if report['duration']:
                                    ui.label(f"运行时长: {self._format_duration(report['duration'])}").classes('col-span-1')
                                else:
                                    ui.label(f"运行时长: -").classes('col-span-1')
                            
                            # 统计信息行 - 使用不同的背景色
                            with ui.card().classes('w-full mt-2 bg-gray-50 rounded-md p-2'):
                                with ui.grid(columns=4).classes('w-full gap-2 text-center'):
                                    # 测试总数
                                    with ui.column().classes('items-center'):
                                        ui.label(str(report['total_tests'])).classes('text-lg font-bold')
                                        ui.label('总数').classes('text-xs text-gray-500')
                                    
                                    # 通过测试数
                                    with ui.column().classes('items-center'):
                                        ui.label(str(report['passed_tests'])).classes('text-lg font-bold text-green-600')
                                        ui.label('通过').classes('text-xs text-gray-500')
                                    
                                    # 失败测试数
                                    with ui.column().classes('items-center'):
                                        ui.label(str(report['failed_tests'])).classes('text-lg font-bold text-red-600')
                                        ui.label('失败').classes('text-xs text-gray-500')
                                    
                                    # 跳过测试数
                                    with ui.column().classes('items-center'):
                                        ui.label(str(report['skipped_tests'])).classes('text-lg font-bold text-gray-500')
                                        ui.label('跳过').classes('text-xs text-gray-500')
                            
                            # 按钮行
                            with ui.row().classes('mt-3 w-full justify-between'):
                                # 左侧：查看报告按钮
                                with ui.row().classes('flex-grow-0'):
                                    if report['report_path']:
                                        view_button = ui.button(
                                            '查看报告',
                                            on_click=lambda path=report['report_path']: self._view_report(path),
                                            color='primary',
                                            icon='article'
                                        ).props('flat rounded')
                                    else:
                                        ui.label('无报告文件').classes('text-gray-400')
                                
                                # 右侧：删除按钮
                                with ui.row().classes('flex-grow-0'):
                                    ui.button(
                                        '删除',
                                        on_click=lambda r=report['run_id'], p=report['report_path']: self._confirm_delete_report(r, p),
                                        color='negative',
                                        icon='delete'
                                    ).props('flat rounded')
    
    def _create_delete_handler(self, run_id: str, report_path: str):
        """创建删除处理器闭包"""
        def delete_handler():
            print(f"删除按钮被点击，Run ID: {run_id}")
            self._confirm_delete_report(run_id, report_path)
        return delete_handler
    
    def _get_status_display(self, status: str) -> str:
        """获取状态的显示文本"""
        status_map = {
            'running': '运行中',
            'completed': '已完成',
            'failed': '失败',
            'stopped': '已停止'
        }
        return status_map.get(status, status)
    
    def _get_status_color(self, status: str) -> str:
        """获取状态对应的颜色"""
        color_map = {
            'running': 'blue',
            'completed': 'green',
            'failed': 'red',
            'stopped': 'orange'
        }
        return color_map.get(status, 'gray')
    
    def _format_duration(self, duration_seconds: float) -> str:
        """格式化时间持续时间"""
        if duration_seconds < 60:
            return f"{duration_seconds:.1f}秒"
        elif duration_seconds < 3600:
            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            return f"{minutes}分{seconds}秒"
        else:
            hours = int(duration_seconds // 3600)
            minutes = int((duration_seconds % 3600) // 60)
            seconds = int(duration_seconds % 60)
            return f"{hours}小时{minutes}分{seconds}秒"
    
    def _confirm_delete_report(self, run_id: str, report_path: str):
        """确认删除报告"""
        print(f"弹出删除确认对话框，Run ID: {run_id}, 报告路径: {report_path}")
        with ui.dialog() as delete_dialog:
            with ui.card().classes('p-4 max-w-md'):
                ui.label('确认删除报告').classes('text-xl font-bold mb-4')
                ui.label(f'确定要删除 Run ID 为 "{run_id}" 的测试报告吗？').classes('mb-4')
                ui.label('此操作将删除：').classes('text-gray-600 mb-2')
                ui.label('• 测试运行记录').classes('text-gray-500 ml-4 mb-1')
                ui.label('• 相关的测试日志').classes('text-gray-500 ml-4 mb-1')
                ui.label('• 报告文件（如果有）').classes('text-gray-500 ml-4 mb-4')
                
                with ui.row().classes('w-full justify-end mt-4'):
                    ui.button('取消', on_click=delete_dialog.close).props('flat')
                    ui.button(
                        '删除',
                        on_click=lambda: self._delete_report(run_id, report_path, delete_dialog),
                        color='negative'
                    )
    
    def _delete_report(self, run_id: str, report_path: str, delete_dialog):
        """删除报告"""
        try:
            # 1. 删除报告文件（如果存在）
            if report_path:
                abs_path = os.path.abspath(report_path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
                    print(f"已删除报告文件: {abs_path}")
            
            # 2. 从数据库中删除相关的测试运行记录和日志
            storage_service.delete_test_run_and_logs(run_id)
            print(f"已删除Run ID为 {run_id} 的数据库记录")
            
            # 关闭对话框
            delete_dialog.close()
            
            # 显示成功消息
            ui.show_notification(f'Run ID "{run_id}" 的测试报告已删除', 3.0)
            
            # 刷新报告列表
            self._load_reports()
            
        except Exception as e:
            # 如果删除失败，显示错误消息
            ui.show_notification(f'删除报告失败: {str(e)}', 5.0)
            # 关闭对话框
            delete_dialog.close()
    
    def _view_report(self, report_path: str):
        """查看测试报告"""
        # 如果报告路径为空，显示提示
        if not report_path:
            ui.show_notification('该测试运行没有生成报告文件', 5.0)
            return
        
        # 检查报告文件是否存在
        abs_path = os.path.abspath(report_path)
        if os.path.exists(abs_path):
            try:
                # 使用webbrowser打开文件
                webbrowser.open(f'file://{abs_path}')
                # 显示成功提示
                ui.show_notification('报告已在新窗口打开', 3.0)
            except Exception as e:
                # 如果打开失败，显示错误提示
                ui.show_notification(f'打开报告失败: {str(e)}', 5.0)
        else:
            # 如果报告文件不存在，显示友好提示
            ui.show_notification(
                '报告文件不存在。可能的原因包括但不限制于：' + chr(10) + '• 测试可能未成功完成' + chr(10) + '• 报告文件可能在其他位置' + chr(10) + '• 报告文件可能被移动或删除', 
                8.0
            )
