import asyncio
import os
import uuid
import logging
from datetime import datetime

from nicegui import ui, app
from typing import List, Dict, Any
from app.models import TestLog, TestRun
from app.services import test_service, storage_service
from config.settings import settings

def _setup_logger():
    logger = logging.getLogger('RemoteTestMonitor.TestMonitor')
    logger.setLevel(logging.DEBUG)
    return logger

logger = _setup_logger()


class TestMonitor:
    def __init__(self):
        self.current_run_id = None
        self.test_logs = []
        self.max_log_lines = 500
        self._pending_status_update = None
        self._rendered_report_ids = set()
    
    def create_dashboard(self):
        """创建测试监控仪表板"""
        with ui.card().classes('w-full'):
            ui.label('测试监控').classes('text-xl font-bold mb-4')
            
            # 测试执行控制
            with ui.row().classes('w-full mb-4'):
                self.test_path_input = ui.input(
                    label='测试路径',
                    value='./tests',  # 添加默认值用于测试
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
                    ui.button('刷新', on_click=self._load_reports, icon='refresh').props('flat')
                
                self.report_container = ui.column().classes('w-full')
                self.report_cards = {}
                self._load_reports()
        
        # 注册测试日志回调
        test_service.register_log_callback(self._update_log)
        test_service.register_status_callback(self._update_test_status)
        
        ui.timer(0.5, self._check_and_process_status)
    
    def _start_test(self):
        """开始执行测试"""
        # 调试信息
        raw_value = self.test_path_input.value
        logger.debug(f"原始输入值: '{raw_value}' (长度: {len(raw_value)})")
        logger.debug(f"字符编码: {[ord(c) for c in raw_value]}")
        
        test_path = self.test_path_input.value.strip()
        logger.debug(f"清理后路径: '{test_path}' (长度: {len(test_path)})")
        
        if not test_path:
            ui.notify('请输入测试路径', type='warning')
            logger.debug("路径为空，停止测试")
            return
        
        # 检测路径是否存在
        if not os.path.exists(test_path):
            ui.notify(f'路径不存在，请检查输入的路径是否正确:\n{test_path}', type='warning', duration=5)
            logger.warning(f"路径不存在: {test_path}")
            return
        
        # 检测路径是否为目录
        if not os.path.isdir(test_path):
            ui.notify(f'路径指向的不是目录，请选择一个有效的测试目录:\n{test_path}', type='warning', duration=5)
            logger.warning(f"路径不是目录: {test_path}")
            return
        
        try:
            # 开始测试
            self.current_run_id = test_service.start_test(test_path)
            logger.debug(f"[DEBUG] 测试已启动: run_id={self.current_run_id}")
            logger.debug(f"[DEBUG] self.test_status 对象存在: {self.test_status is not None}")
            
            # 立即刷新报告列表以显示新测试
            self._load_reports()
            
            # 更新UI状态
            self.start_button.disable()
            self.stop_button.enable()
            logger.debug(f"[DEBUG] 更新UI状态: test_status.text = '测试正在执行...'")
            self.test_status.text = f'测试正在执行... (Run ID: {self.current_run_id})'
            logger.debug(f"[DEBUG] 更新后的text值: {self.test_status.text}")
            self.test_status.classes(remove='text-red-500 text-green-500').classes('text-blue-500')
            logger.debug(f"[DEBUG] UI状态更新完成")
            
            ui.notify(f'测试已开始: {test_path}', type='success')
        except Exception as e:
            logger.error(f"[DEBUG] 测试启动异常: {e}")
            import traceback
            logger.error(f"启动异常堆栈: {traceback.format_exc()}")
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
        logger.debug(f"[DEBUG] _update_log 被调用: run_id={test_log.run_id}, current_run_id={self.current_run_id}")
        
        if not self.current_run_id:
            logger.debug(f"[DEBUG] current_run_id 为 None，自动设置为当前日志的 run_id")
            self.current_run_id = test_log.run_id
        
        if test_log.run_id != self.current_run_id:
            logger.debug(f"[DEBUG] 日志被跳过: run_id不匹配 ({test_log.run_id} != {self.current_run_id})")
            return
        
        self.test_logs.append(test_log)
        
        log_message = f"[{test_log.timestamp.strftime('%H:%M:%S')}] {test_log.message}"
        logger.debug(f"[DEBUG] 推送日志到UI: {log_message[:50]}...")
        
        async def update_ui():
            logger.debug(f"[DEBUG] 执行UI更新: {log_message[:50]}...")
            try:
                self.log_output.push(log_message)
                logger.debug(f"[DEBUG] UI日志更新成功，当前日志数量: {len(self.test_logs)}")
            except Exception as e:
                logger.error(f"日志输出失败: {e}")
            
            if len(self.test_logs) > self.max_log_lines:
                try:
                    self.log_output.clear()
                    for log in self.test_logs[-self.max_log_lines:]:
                        log_msg = f"[{log.timestamp.strftime('%H:%M:%S')}] {log.message}"
                        self.log_output.push(log_msg)
                except Exception as e:
                    logger.error(f"清除日志失败: {e}")
        
        try:
            loop = asyncio.get_running_loop()
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)
            future = asyncio.run_coroutine_threadsafe(update_ui(), loop)
            result = future.result(timeout=5)
        except Exception as e:
            logger.error(f"UI更新失败: {e}")
            asyncio.run(update_ui())
    
    def _update_test_status(self, test_run: TestRun):
        """更新测试状态"""
        logger.debug(f"[STATUS-CB] _update_test_status 被调用: test_run.run_id={test_run.run_id}, self.current_run_id={self.current_run_id}, status={test_run.status}")
        
        if not self.current_run_id:
            if test_run.status == 'running':
                logger.debug(f"[STATUS-CB] current_run_id 为 None 但测试已开始，自动设置为当前测试 run_id")
                self.current_run_id = test_run.run_id
            else:
                logger.debug(f"[STATUS-CB] current_run_id 为 None 且测试未运行，忽略状态回调")
                return
        
        if test_run.run_id != self.current_run_id:
            logger.debug(f"[DEBUG] run_id 不匹配，忽略状态回调")
            return
        
        self._pending_status_update = test_run
    
    def _check_and_process_status(self):
        """检查并处理挂起的状态更新"""
        if self._pending_status_update is None:
            return
        
        test_run = self._pending_status_update
        self._pending_status_update = None
        
        logger.info(f"[STATUS] 处理状态更新: run_id={test_run.run_id}, status={test_run.status}")
        
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
        
        self.start_button.enable()
        self.stop_button.disable()
        
        logger.info(f"[STATUS] 清除 current_run_id: {self.current_run_id}")
        self.current_run_id = None
        
        logger.info(f"[STATUS] 调用 _load_reports() 刷新UI")
        self._load_reports()
        logger.info(f"[STATUS] _load_reports() 执行完成")
    
    def _download_logs(self, run_id: str = None):
        """下载测试日志"""
        target_run_id = run_id or self.current_run_id
        
        if run_id:
            log_file_path = os.path.join(settings.TEST_REPORTS_PATH, f"{run_id}.log")
            
            if not os.path.exists(log_file_path):
                ui.notify(f'日志文件不存在: {log_file_path}', type='warning', duration=5)
                return
            
            if os.path.getsize(log_file_path) == 0:
                ui.notify(f'日志文件为空', type='info', duration=5)
                return
            
            try:
                ui.download(
                    src=log_file_path,
                    filename=f'test_logs_{run_id}.txt',
                    media_type='text/plain'
                )
                logger.info(f"日志下载成功: {run_id}")
                return
            except Exception as e:
                ui.notify(f'下载日志失败: {str(e)}', type='error')
                return
        
        if self.test_logs:
            try:
                log_content = '\n'.join([
                    f"[{log.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {log.message}"
                    for log in self.test_logs
                ])
                if target_run_id:
                    filename = f'test_logs_{target_run_id}.txt'
                else:
                    filename = f'test_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
                
                temp_file = os.path.join(settings.TEMP_PATH, f"download_{uuid.uuid4().hex}.txt")
                os.makedirs(settings.TEMP_PATH, exist_ok=True)
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(log_content)
                
                ui.download(
                    src=temp_file,
                    filename=filename,
                    media_type='text/plain'
                )
                logger.info(f"日志下载成功，共 {len(self.test_logs)} 条记录")
                return
            except Exception as e:
                ui.notify(f'下载日志失败: {str(e)}', type='error')
                return
        
        if not target_run_id:
            ui.notify('请先执行测试以生成日志', type='warning')
            return
        
        log_file_path = os.path.join(settings.TEST_REPORTS_PATH, f"{target_run_id}.log")
        
        if not os.path.exists(log_file_path):
            ui.notify(f'日志文件: {log_file_path} 不存在', type='warning', duration=5)
            return
        
        if os.path.getsize(log_file_path) == 0:
            ui.notify(f'日志文件: {log_file_path} 为空', type='info', duration=5)
            return
        
        try:
            if os.path.exists(log_file_path):
                ui.download(
                    src=log_file_path,
                    filename=f'test_logs_{target_run_id}.txt',
                    media_type='text/plain'
                )
            else:
                ui.notify(f'日志文件: {log_file_path} 已被移动或删除', type='warning', duration=5)
        except Exception as e:
            ui.notify(f'下载日志失败: {str(e)}', type='error')
    
    def _load_reports(self):
        """加载测试报告列表"""
        logger.info("开始加载报告列表")
        
        # 从数据库获取所有测试运行记录
        test_runs = storage_service.get_all_test_runs()
        logger.info(f"从数据库获取到 {len(test_runs)} 条测试记录")
        
        # 格式化数据为前端需要的格式
        reports = []
        for run in test_runs:
            duration = None
            if run.end_time:
                duration = (run.end_time - run.start_time).total_seconds()
            
            status_display = self._get_status_display(run.status)
            start_time_str = run.start_time.strftime('%Y-%m-%d %H:%M:%S')
            
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
                'report_path': run.report_path,
                'start_datetime': run.start_time  # 用于排序
            })
        
        # 按状态和时间排序：运行中的排在最前面，其他按开始时间倒序
        reports.sort(key=lambda x: (x['status'] != 'running', -x['start_datetime'].timestamp()))
        
        current_report_ids = {r['run_id'] for r in reports}
        new_report_ids = current_report_ids - set(self.report_cards.keys())
        removed_report_ids = set(self.report_cards.keys()) - current_report_ids
        
        if not reports:
            logger.info("没有报告数据，清空所有报告")
            for run_id in list(self.report_cards.keys()):
                self.report_cards[run_id]['card'].delete()
                del self.report_cards[run_id]
        elif new_report_ids:
            logger.info(f"发现 {len(new_report_ids)} 个新报告需要渲染")
            for run_id in list(self.report_cards.keys()):
                self.report_cards[run_id]['card'].delete()
                del self.report_cards[run_id]
            self._render_reports(reports)
        elif removed_report_ids:
            logger.info(f"发现 {len(removed_report_ids)} 个报告已被移除")
            for run_id in removed_report_ids:
                if run_id in self.report_cards:
                    self.report_cards[run_id]['card'].delete()
                    del self.report_cards[run_id]
        else:
            logger.debug(f"执行 _update_changed_reports，报告数量: {len(reports)}")
            updated_count = self._update_changed_reports(reports)
            logger.debug(f"_update_changed_reports 返回更新数量: {updated_count}")
            if updated_count > 0:
                logger.info(f"有 {updated_count} 个报告数据已更新，更新了统计信息")
            else:
                logger.info("没有新报告，数据无变化，跳过渲染")
        
        logger.info(f"当前已渲染报告数: {len(self.report_cards)}")
    
    def _render_reports(self, reports):
        """渲染报告列表到UI（按排序顺序：运行中在前，时间倒序）"""
        logger.info(f"开始渲染 {len(reports)} 个报告")
        
        for report in reports:
            run_id = report['run_id']
            logger.info(f"渲染报告: {run_id}")
            
            total = report['total_tests']
            passed = report['passed_tests']
            failed = report['failed_tests']
            skipped = report['skipped_tests']
            success_rate = (passed / (total - skipped) * 100) if (total - skipped) > 0 else 100
            
            db_status = report['status']
            
            if db_status == 'running':
                effective_status = 'running'
            elif db_status == 'completed':
                if success_rate < 95:
                    effective_status = 'failed'
                else:
                    effective_status = 'completed'
            else:
                effective_status = db_status
            
            with self.report_container:
                with ui.card().classes('w-full mb-4 border rounded-lg shadow-sm hover:shadow-md transition-all duration-200') as card:
                    with ui.column().classes('p-3 w-full'):
                        with ui.row().classes('justify-between items-center w-full mb-2'):
                            ui.label(f"测试: {report['test_path']}").classes('font-semibold text-lg')
                            status_color = self._get_status_color(effective_status)
                            if effective_status == 'running':
                                status_display = '运行中'
                            elif effective_status == 'failed':
                                status_display = '失败'
                            elif effective_status == 'completed':
                                if failed == 0:
                                    status_display = '通过'
                                else:
                                    status_display = '完成'
                            else:
                                status_display = '完成'
                            status_badge = ui.badge(status_display, color=status_color)
                            
                            if effective_status == 'running':
                                progress = ((passed + failed) / total * 100) if total > 0 else 0
                                status_badge.tooltip(f'测试运行中 - 已完成: {passed + failed} / {total} ({progress:.1f}%)')
                            elif effective_status == 'completed':
                                if failed == 0:
                                    status_badge.tooltip('测试通过 - 退出码为0，所有用例执行成功')
                                else:
                                    status_badge.tooltip(f'测试完成 - 退出码为0且成功率≥95%({success_rate:.1f}%)，失败用例: {failed}个')
                            elif effective_status == 'failed':
                                exit_code_info = report.get('exit_code', '')
                                if success_rate < 95:
                                    status_badge.tooltip(f'测试失败 - 成功率<95%({success_rate:.1f}%)，失败用例: {failed}个')
                                else:
                                    status_badge.tooltip(f'测试失败 - 退出码非0({exit_code_info})，成功率: {success_rate:.1f}%')
                        
                        with ui.grid(columns=3).classes('w-full gap-2 text-sm text-gray-500'):
                            ui.label(f"开始时间: {report['start_time']}").classes('col-span-1')
                            ui.label(f"Run ID: {run_id}").classes('col-span-1')
                            if report['duration']:
                                duration_label = ui.label(f"运行时长: {self._format_duration(report['duration'])}").classes('col-span-1')
                            else:
                                duration_label = ui.label(f"运行时长: -").classes('col-span-1')
                        
                        with ui.card().classes('w-full mt-2 bg-gray-50 rounded-md p-2'):
                            with ui.grid(columns=4).classes('w-full gap-2 text-center'):
                                with ui.column().classes('items-center'):
                                    total_label = ui.label(str(total)).classes('text-lg font-bold')
                                    ui.label('总数').classes('text-xs text-gray-500')
                                
                                with ui.column().classes('items-center'):
                                    passed_label = ui.label(str(passed)).classes('text-lg font-bold text-green-600')
                                    ui.label('通过').classes('text-xs text-gray-500')
                                
                                with ui.column().classes('items-center'):
                                    failed_label = ui.label(str(failed)).classes('text-lg font-bold text-red-600')
                                    ui.label('失败').classes('text-xs text-gray-500')
                                
                                with ui.column().classes('items-center'):
                                    skipped_label = ui.label(str(skipped)).classes('text-lg font-bold text-gray-500')
                                    ui.label('跳过').classes('text-xs text-gray-500')
                        
                        with ui.row().classes('mt-3 w-full justify-between'):
                            with ui.row().classes('flex-grow-0 gap-2'):
                                if report['report_path']:
                                    def create_view_handler(report_path, run_id):
                                        def view_handler():
                                            self._view_report(report_path, run_id)
                                        return view_handler
                                    
                                    ui.button(
                                        '查看报告',
                                        on_click=create_view_handler(report['report_path'], report['run_id']),
                                        color='primary',
                                        icon='article'
                                    ).props('flat rounded')
                                else:
                                    ui.label('无报告文件').classes('text-gray-400')
                                
                                def create_download_handler(run_id):
                                    def download_handler():
                                        self._download_logs(run_id)
                                    return download_handler
                                
                                ui.button(
                                    '下载日志',
                                    on_click=create_download_handler(report['run_id']),
                                    color='secondary',
                                    icon='download'
                                ).props('flat rounded')
                            
                            with ui.row().classes('flex-grow-0'):
                                def create_delete_handler(run_id, report_path):
                                    def delete_handler():
                                        self._confirm_delete_report(run_id, report_path)
                                    return delete_handler
                                
                                ui.button(
                                    '删除',
                                    on_click=create_delete_handler(report['run_id'], report['report_path']),
                                    color='negative',
                                    icon='delete'
                                ).props('flat rounded')
                    
                    self.report_cards[run_id] = {
                        'card': card,
                        'data': report.copy(),
                        'status_badge': status_badge,
                        'duration_label': duration_label,
                        'total_label': total_label,
                        'passed_label': passed_label,
                        'failed_label': failed_label,
                        'skipped_label': skipped_label
                    }
        
        logger.info(f"✅ 报告渲染完成，总共 {len(reports)} 个报告")
    
    def _update_changed_reports(self, reports: list) -> int:
        """更新数据有变化的报告卡片（实时更新统计信息）"""
        updated_count = 0
        
        for report in reports:
            run_id = report['run_id']
            if run_id not in self.report_cards:
                logger.debug(f"[UPDATE] 跳过 {run_id}，不在 report_cards 中")
                continue
            
            card_info = self.report_cards[run_id]
            old_data = card_info['data']
            
            has_changes = (
                old_data['total_tests'] != report['total_tests'] or
                old_data['passed_tests'] != report['passed_tests'] or
                old_data['failed_tests'] != report['failed_tests'] or
                old_data['skipped_tests'] != report['skipped_tests'] or
                old_data['status'] != report['status'] or
                old_data['duration'] != report['duration']
            )
            
            if not has_changes:
                logger.debug(f"[UPDATE] 跳过 {run_id}，无变化: status={report['status']}, old_status={old_data['status']}")
                continue
            
            logger.info(f"[UPDATE] 检测到 {run_id} 有变化: status={report['status']} -> old_status={old_data['status']}")
            total = report['total_tests']
            passed = report['passed_tests']
            failed = report['failed_tests']
            skipped = report['skipped_tests']
            success_rate = (passed / (total - skipped) * 100) if (total - skipped) > 0 else 100
            
            db_status = report['status']
            
            if db_status == 'running':
                effective_status = 'running'
            elif db_status == 'completed':
                if success_rate < 95:
                    effective_status = 'failed'
                else:
                    effective_status = 'completed'
            else:
                effective_status = db_status
            
            card_info['total_label'].set_text(str(total))
            card_info['passed_label'].set_text(str(passed))
            card_info['failed_label'].set_text(str(failed))
            card_info['skipped_label'].set_text(str(skipped))
            
            if report['duration']:
                card_info['duration_label'].set_text(f"运行时长: {self._format_duration(report['duration'])}")
            else:
                card_info['duration_label'].set_text(f"运行时长: -")
            
            status_color = self._get_status_color(effective_status)
            if effective_status == 'running':
                status_display = '运行中'
            elif effective_status == 'failed':
                status_display = '失败'
            elif effective_status == 'completed':
                if failed == 0:
                    status_display = '通过'
                else:
                    status_display = '完成'
            else:
                status_display = '完成'
            
            card_info['status_badge'].set_text(status_display)
            card_info['status_badge'].props(f'color={status_color}')
            
            if effective_status == 'running':
                progress = ((passed + failed) / total * 100) if total > 0 else 0
                card_info['status_badge'].tooltip(f'测试运行中 - 已完成: {passed + failed} / {total} ({progress:.1f}%)')
            elif effective_status == 'completed':
                if failed == 0:
                    card_info['status_badge'].tooltip('测试通过 - 退出码为0，所有用例执行成功')
                else:
                    card_info['status_badge'].tooltip(f'测试完成 - 退出码为0且成功率≥95%({success_rate:.1f}%)，失败用例: {failed}个')
            elif effective_status == 'failed':
                exit_code_info = report.get('exit_code', '')
                if success_rate < 95:
                    card_info['status_badge'].tooltip(f'测试失败 - 成功率<95%({success_rate:.1f}%)，失败用例: {failed}个')
                else:
                    card_info['status_badge'].tooltip(f'测试失败 - 退出码非0({exit_code_info})，成功率: {success_rate:.1f}%')
            
            card_info['data'] = report.copy()
            updated_count += 1
        
        return updated_count
    
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
        logger.info(f"🗺️ 触发确认删除对话框 - run_id={run_id}, report_path={report_path}")
        logger.info(f"📅 对话框创建时间={datetime.now()}")
        
        try:
            with ui.dialog() as delete_dialog:
                logger.info(f"🔲 UI对话框对象创建成功 - 对话框ID={id(delete_dialog)}")
                
                with ui.card().classes('p-4 max-w-md'):
                    logger.info(f"📦 对话框卡片创建成功")
                    
                    ui.label('确认删除报告').classes('text-xl font-bold mb-4')
                    ui.label(f'确定要删除 Run ID 为 "{run_id}" 的测试报告吗？').classes('mb-4')
                    ui.label('此操作将删除：').classes('text-gray-600 mb-2')
                    ui.label('• 测试运行记录').classes('text-gray-500 ml-4 mb-1')
                    ui.label('• 相关的测试日志').classes('text-gray-500 ml-4 mb-1')
                    ui.label('• 报告文件（如果有）').classes('text-gray-500 ml-4 mb-4')
                    
                    with ui.row().classes('w-full justify-end mt-4'):
                        logger.info(f"📝 创建取消按钮")
                        ui.button('取消', on_click=delete_dialog.close).props('flat')
                        logger.info(f"📝 创建确认删除按钮")
                        
                        # 修复lambda函数变量绑定问题 - 添加超详细debug信息
                        def create_delete_confirmation_handler(run_id, report_path, delete_dialog):
                            logger.info(f"🔧 创建确认删除处理器 - run_id={run_id}, report_path={report_path}, 对话框ID={id(delete_dialog)}")
                            def delete_confirmation_handler():
                                logger.info(f"🖱️ 确认删除按钮被点击！事件触发 - run_id={run_id}")
                                logger.info(f"📋 确认删除详情 - 当前时间={datetime.now()}, 处理器ID={id(delete_confirmation_handler)}")
                                logger.info(f"🚀 开始调用 _delete_report 函数")
                                logger.info(f"📁 传递的参数 - run_id={run_id}, report_path={report_path}, delete_dialog={id(delete_dialog)}")
                                try:
                                    self._delete_report(run_id, report_path, delete_dialog)
                                    logger.info(f"✅ _delete_report 调用成功")
                                except Exception as e:
                                    logger.error(f"❌ _delete_report 调用失败: {str(e)}", exc_info=True)
                            return delete_confirmation_handler
                        
                        confirm_delete_button = ui.button(
                            '删除',
                            on_click=create_delete_confirmation_handler(run_id, report_path, delete_dialog),
                            color='negative'
                        )
                        logger.info(f"✅ 确认删除按钮创建成功 - 按钮ID={id(confirm_delete_button)}")
                        logger.info(f"📍 确认删除按钮已绑定到run_id={run_id}")
                        
                logger.info(f"🎯 对话框UI构建完成，准备显示")
                logger.info(f"📢 调用 delete_dialog.open() 显示对话框")
                delete_dialog.open()
                logger.info(f"✅ 确认删除对话框创建并显示完成")
                
        except Exception as e:
            logger.error(f"❌ 创建确认删除对话框失败: {str(e)}", exc_info=True)
            ui.notify(f'创建删除对话框失败: {str(e)}', type='error')
    
    def _delete_report(self, run_id: str, report_path: str, delete_dialog):
        """删除报告"""
        logger.info(f"🔥 开始执行删除报告 - run_id={run_id}, report_path={report_path}")
        logger.info(f"📋 删除流程详情 - 当前时间={datetime.now()}, 对话框ID={id(delete_dialog)}")
        logger.info(f"🔍 接收到的参数验证 - run_id类型={type(run_id)}, report_path类型={type(report_path)}, delete_dialog类型={type(delete_dialog)}")
        
        try:
            deleted_files = []
            logger.info(f"📝 初始化删除文件列表: {deleted_files}")
            
            # 1. 从数据库中删除相关的测试运行记录和日志
            logger.info(f"🗃️ 步骤1: 开始从数据库删除记录")
            logger.info(f"🔍 查询数据库 - run_id={run_id}")
            logger.info(f"📞 调用 storage_service.delete_test_run() 方法")
            
            success = storage_service.delete_test_run(run_id)
            
            logger.info(f"📊 数据库删除结果 - success={success}, run_id={run_id}")
            
            if not success:
                logger.error(f"❌ 数据库删除失败 - run_id={run_id}")
                logger.error(f"📋 失败详情 - 可能原因：网络问题、数据库锁定、记录不存在")
                
                # 关闭对话框
                logger.info(f"🚪 关闭删除确认对话框")
                delete_dialog.close()
                logger.info(f"✅ 对话框已关闭")
                
                # 显示错误消息
                logger.info(f"📢 显示错误通知消息")
                ui.notify(f'删除数据库记录失败，请检查网络连接或联系管理员', type='error')
                logger.info(f"✅ 错误通知已显示")
                
                # 刷新报告列表 - 即使失败也需要刷新以确保数据一致性
                logger.info(f"🔄 刷新报告列表（失败后）")
                ui.timer(0.1, self._load_reports, once=True)
                logger.info(f"✅ 报告列表刷新定时器已启动（失败后）")
                return
            
            logger.info(f"✅ 数据库删除成功 - run_id={run_id}")
            
            # 2. 删除报告文件（如果存在）- 智能路径处理
            logger.info(f"📁 步骤2: 开始删除报告文件")
            logger.info(f"🔍 检查报告路径 - report_path='{report_path}', 路径类型={type(report_path)}")
            
            if report_path:
                logger.info(f"📋 报告路径有效，开始文件删除流程")
                logger.info(f"🗂️ 尝试删除报告文件: {report_path}")
                
                # 尝试原始路径
                abs_path = os.path.abspath(report_path)
                logger.info(f"🔍 检查原始路径: {abs_path}")
                logger.info(f"📂 原始路径存在性检查: {os.path.exists(abs_path)}")
                if os.path.exists(abs_path):
                    logger.info(f"✅ 原始路径文件存在，尝试删除")
                    try:
                        os.remove(abs_path)
                        deleted_files.append(abs_path)
                        logger.info(f"✅ 已删除报告文件（原始路径）: {abs_path}")
                        logger.info(f"📝 已删除文件列表更新: {deleted_files}")
                    except Exception as e:
                        logger.error(f"❌ 删除原始路径文件失败: {str(e)}")
                        logger.error(f"🔍 失败详情 - 异常类型={type(e).__name__}")
                
                # 如果原始路径不存在，尝试标准化路径
                if not deleted_files:
                    logger.info(f"🔄 原始路径未找到，尝试标准化路径")
                    normalized_path = report_path.replace('\\', os.sep).replace('/', os.sep)
                    normalized_abs_path = os.path.abspath(normalized_path)
                    logger.info(f"🔍 检查标准化路径: {normalized_abs_path}")
                    logger.info(f"📂 标准化路径存在性检查: {os.path.exists(normalized_abs_path)}")
                    if os.path.exists(normalized_abs_path):
                        logger.info(f"✅ 标准化路径文件存在，尝试删除")
                        try:
                            os.remove(normalized_abs_path)
                            deleted_files.append(normalized_abs_path)
                            logger.info(f"✅ 已删除报告文件（标准化路径）: {normalized_abs_path}")
                            logger.info(f"📝 已删除文件列表更新: {deleted_files}")
                        except Exception as e:
                            logger.error(f"❌ 删除标准化路径文件失败: {str(e)}")
                            logger.error(f"🔍 失败详情 - 异常类型={type(e).__name__}")
                
                # 如果仍然没有找到文件，尝试在标准报告目录中查找匹配的文件
                if not deleted_files:
                    logger.info(f"🔄 标准化路径也未找到，尝试标准报告目录")
                    try:
                        standard_report_path = os.path.join(settings.TEST_REPORTS_PATH, f"report_{run_id}.html")
                        logger.info(f"🔍 检查标准路径: {standard_report_path}")
                        logger.info(f"📂 标准路径存在性检查: {os.path.exists(standard_report_path)}")
                        if os.path.exists(standard_report_path):
                            logger.info(f"✅ 标准路径文件存在，尝试删除")
                            try:
                                os.remove(standard_report_path)
                                deleted_files.append(standard_report_path)
                                logger.info(f"✅ 已删除报告文件（标准路径）: {standard_report_path}")
                                logger.info(f"📝 已删除文件列表更新: {deleted_files}")
                            except Exception as e:
                                logger.error(f"❌ 删除标准路径文件失败: {str(e)}")
                                logger.error(f"🔍 失败详情 - 异常类型={type(e).__name__}")
                        else:
                            logger.info(f"ℹ️ 标准路径文件不存在，跳过")
                    except Exception as e:
                        logger.error(f"❌ 加载配置失败: {str(e)}")
                        logger.error(f"🔍 配置加载失败详情 - 可能原因：配置文件不存在、格式错误")
                
                if not deleted_files:
                    logger.warning(f"⚠️ 未找到报告文件，可能已被删除或路径错误: report_path={report_path}")
                    logger.warning(f"🔍 路径分析 - 原始路径={report_path}, 绝对路径={abs_path}")
                    logger.warning(f"ℹ️ 这可能是正常情况（文件已被删除或路径记录错误）")
            else:
                logger.info(f"ℹ️ 报告路径为空，跳过文件删除")
            
            # 3. 删除日志文件
            logger.info(f"📁 步骤3: 开始删除日志文件")
            log_file_path = os.path.join(settings.TEST_REPORTS_PATH, f"{run_id}.log")
            logger.info(f"🔍 检查日志文件路径: {log_file_path}")
            if os.path.exists(log_file_path):
                try:
                    os.remove(log_file_path)
                    deleted_files.append(log_file_path)
                    logger.info(f"✅ 已删除日志文件: {log_file_path}")
                except Exception as e:
                    logger.error(f"❌ 删除日志文件失败: {str(e)}")
            else:
                logger.info(f"ℹ️ 日志文件不存在，跳过: {log_file_path}")
            
            # 4. 构建成功消息并更新UI
            logger.info(f"📊 步骤4: 构建成功消息和UI更新")
            logger.info(f"📋 已删除测试运行记录: run_id={run_id}")
            logger.info(f"📝 已删除文件列表: {deleted_files}")
            
            # 构建成功消息
            if deleted_files:
                file_list = '\n'.join([f"• {os.path.basename(f)}" for f in deleted_files])
                message = f'Run ID "{run_id}" 的测试报告已删除\n已删除文件:\n{file_list}'
                logger.info(f"📢 构建成功消息 - 包含文件列表: {len(deleted_files)} 个文件")
            else:
                message = f'Run ID "{run_id}" 的测试记录已删除（报告文件不存在或已删除）'
                logger.info(f"📢 构建成功消息 - 无文件删除")
            
            logger.info(f"📋 最终成功消息: {message}")
            
            # 关闭对话框
            logger.info(f"🚪 关闭删除确认对话框")
            delete_dialog.close()
            logger.info(f"✅ 对话框已关闭")
            
            # 显示成功消息
            logger.info(f"📢 显示成功通知消息")
            ui.notify(message, type='success', duration=5)
            logger.info(f"✅ 成功通知已显示")
            
            # 刷新报告列表 - 使用定时器确保UI更新
            logger.info(f"🔄 刷新报告列表")
            ui.timer(0.1, self._load_reports, once=True)
            logger.info(f"✅ 报告列表刷新定时器已启动")
            
            logger.info(f"🎉 删除报告流程全部完成 - run_id={run_id}")
            
        except Exception as e:
            # 如果删除失败，显示错误消息
            logger.error(f"💥 删除报告过程中发生异常: {str(e)}", exc_info=True)
            logger.error(f"🔍 异常详情 - 异常类型={type(e).__name__}, run_id={run_id}")
            logger.error(f"📋 异常堆栈跟踪已记录")
            
            try:
                # 尝试关闭对话框
                logger.info(f"🚪 尝试关闭对话框（异常处理）")
                delete_dialog.close()
                logger.info(f"✅ 对话框已关闭")
            except Exception as dialog_e:
                logger.error(f"❌ 关闭对话框失败: {str(dialog_e)}")
            
            # 显示错误消息
            logger.info(f"📢 显示错误通知消息（异常处理）")
            ui.notify(f'删除报告失败: {str(e)}，请检查文件权限或磁盘空间', type='error')
            logger.info(f"✅ 错误通知已显示")
            
            logger.error(f"💔 删除报告流程异常结束 - run_id={run_id}")
            logger.error(f"删除报告失败: {str(e)}", exc_info=True)
            
            # 关闭对话框
            delete_dialog.close()
            
            # 显示错误消息
            ui.notify(f'删除报告失败: {str(e)}，请检查文件权限或磁盘空间', type='error')
    
    def _view_report(self, report_path: str, run_id: str):
        """查看测试报告"""
        # 如果报告路径为空，显示提示
        if not report_path:
            ui.notify('该测试运行没有生成报告文件', type='warning')
            return
        
        # 检查报告文件是否存在
        abs_path = os.path.abspath(report_path)
        if os.path.exists(abs_path):
            try:
                # 使用新窗口打开报告页面
                ui.run_javascript(f"window.open('/report/{run_id}', '_blank');")
                # 显示成功提示
                ui.notify('报告已在新窗口打开', type='success')
            except Exception as e:
                # 如果打开失败，显示错误提示
                ui.notify(f'打开报告失败: {str(e)}', type='error')
        else:
            # 如果报告文件不存在，显示友好提示
            ui.notify(
                '报告文件不存在，可能的原因:\n  • 测试可能未成功完成\n  • 报告文件可能在其他位置\n  • 报告文件可能被移动或删除', 
                type='warning',
                duration=8
            )
