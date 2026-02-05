import asyncio
import os
import uuid
import logging
from datetime import datetime

from nicegui import ui, app
from typing import List, Dict, Any, Optional
from app.models import TestLog, TestRun, RemoteMachine
from app.services import test_service, storage_service, remote_machine_service
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
        self._machines = []
        self._load_machines()
    
    def _load_machines(self):
        """加载机器列表"""
        self._machines = remote_machine_service.get_all_machines()
    
    def create_dashboard(self):
        """创建测试监控仪表板"""
        with ui.card().classes('w-full'):
            ui.label('测试监控').classes('text-2xl font-bold mb-4')
            
            with ui.tabs().classes('w-full mb-4') as self.tabs:
                self.tab_test = ui.tab('测试执行', icon='play_arrow').classes('text-lg')
                self.tab_machine = ui.tab('机器管理', icon='computer').classes('text-lg')
            
            with ui.tab_panels(self.tabs, value=self.tab_test).classes('w-full'):
                with ui.tab_panel(self.tab_test):
                    self._create_test_execution_panel()
                
                with ui.tab_panel(self.tab_machine):
                    self._create_machine_management_panel()
        
        test_service.register_log_callback(self._update_log)
        test_service.register_status_callback(self._update_test_status)
        
        ui.timer(0.5, self._check_and_process_status)
    
    def _create_test_execution_panel(self):
        """创建测试执行面板"""
        with ui.row().classes('w-full mb-4 items-center'):
            ui.label('执行模式:').classes('mr-2')
            self.execution_mode = ui.toggle(['本地', '远程'], value='本地', on_change=self._on_execution_mode_change).classes('mr-4')
            
            self.machine_select_container = ui.row().classes('items-center').style('display: none;')
            with self.machine_select_container:
                ui.label('选择机器:').classes('mr-2')
                self.machine_select = ui.select(
                    options={m.machine_id: f"{m.name} ({m.host})" for m in self._machines},
                    label='机器',
                    on_change=self._on_machine_select
                ).classes('w-64')
                self.test_remote_path_input = ui.input(
                    label='远程测试路径',
                    value='./tests',
                    placeholder='例如: ./tests 或 C:\\tests'
                ).classes('w-80 ml-2').style('display: none;')
        
        with ui.row().classes('w-full mb-4'):
            self.test_path_input = ui.input(
                label='测试路径',
                value='./tests',
                placeholder='例如: ./tests 或 tests/test_example.py'
            ).classes('flex-grow mr-2')
            
            self.start_button = ui.button('开始测试', on_click=self._start_test).classes('mr-2')
            self.stop_button = ui.button('停止测试', on_click=self._stop_test)
            self.stop_button.disable()
        
        with ui.card().classes('w-full mb-4'):
            self.test_status = ui.label('等待测试执行').classes('text-lg')
        
        with ui.card().classes('w-full'):
            ui.label('测试日志').classes('text-lg font-semibold mb-2')
            
            self.log_output = ui.log().classes('w-full h-96')
            
            with ui.row().classes('mt-2'):
                ui.button('清空日志', on_click=lambda: self.log_output.clear())
                ui.button('下载日志', on_click=self._download_logs).classes('ml-2')
        
        # 测试执行统计卡片
        with ui.card().classes('w-full mt-4'):
            ui.label('测试执行统计').classes('text-lg font-semibold mb-4')
            
            with ui.row().classes('w-full mb-4 items-center'):
                ui.label('时间范围:').classes('mr-2')
                self.time_range_select = ui.select(
                    options={'1h': '最近1小时', '24h': '最近24小时', '7d': '最近7天', '30d': '最近30天'},
                    value='24h',
                    on_change=self._on_time_range_change
                ).classes('w-40 mr-4')
                ui.button('刷新统计', icon='refresh', on_click=self._refresh_test_statistics)
            
            # 测试通过率趋势图
            self.test_pass_rate_chart = ui.echart({
                'title': {
                    'text': '测试通过率趋势',
                    'left': 'center'
                },
                'tooltip': {
                    'trigger': 'axis',
                    'formatter': '{b}<br/>通过率: {c}%'
                },
                'xAxis': {
                    'type': 'category',
                    'data': [],
                    'axisLabel': {
                        'rotate': 45,
                        'fontSize': 8
                    }
                },
                'yAxis': {
                    'type': 'value',
                    'name': '通过率(%)',
                    'min': 0,
                    'max': 100,
                    'interval': 10
                },
                'series': [{
                    'name': '通过率',
                    'type': 'line',
                    'data': [],
                    'smooth': True,
                    'itemStyle': {
                        'color': '#faad14'
                    },
                    'lineStyle': {
                        'color': '#faad14'
                    },
                    'areaStyle': {
                        'color': {
                            'type': 'linear',
                            'x': 0,
                            'y': 0,
                            'x2': 0,
                            'y2': 1,
                            'colorStops': [
                                {'offset': 0, 'color': 'rgba(250, 173, 20, 0.3)'},
                                {'offset': 1, 'color': 'rgba(250, 173, 20, 0.05)'}
                            ]
                        }
                    }
                }]
            }).classes('w-full h-64')
        
        with ui.card().classes('w-full mt-4'):
            with ui.row().classes('w-full justify-between items-center mb-2'):
                ui.label('测试报告').classes('text-lg font-semibold')
                with ui.row().classes('gap-2'):
                    ui.button('刷新', on_click=self._load_reports, icon='refresh').props('flat')
                    ui.button('清空报告/日志', on_click=self._show_clear_confirm_dialog, icon='delete').props('flat color=red')
            
            self.report_container = ui.column().classes('w-full')
            self.report_cards = {}
            self._load_reports()
    
    def _create_machine_management_panel(self):
        """创建机器管理面板"""
        self._selected_machine_ids = []  # 存储多个选中的机器ID
        
        with ui.row().classes('w-full mb-4'):
            ui.button('添加机器', on_click=self._show_add_machine_dialog, icon='add').classes('mr-2')
            ui.button('刷新', on_click=self._refresh_machine_list, icon='refresh')
        
        # 机器状态分布饼图
        with ui.card().classes('w-full bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-all duration-200 mb-6'):
            ui.label('机器状态分布').classes('text-lg font-semibold mb-4 text-gray-700')
            self.machine_status_chart = ui.echart({
                'title': {
                    'text': '机器状态分布',
                    'left': 'center'
                },
                'tooltip': {
                    'trigger': 'item',
                    'formatter': '{b}: {c} ({d}%)'
                },
                'legend': {
                    'orient': 'vertical',
                    'left': 'left'
                },
                # 统一状态颜色：与表格中显示的颜色保持一致
                'color': ['#d1fae5', '#fee2e2', '#fef3c7'],  # 浅绿色(在线), 浅红色(离线), 浅黄色(未知)
                'series': [{
                    'name': '机器状态',
                    'type': 'pie',
                    'radius': '60%',
                    'center': ['50%', '50%'],
                    'data': [],
                    'label': {
                        'formatter': '{b} {c}',  # 在饼图连线上增加统计计数
                        'position': 'outside'
                    },
                    'emphasis': {
                        'itemStyle': {
                            'shadowBlur': 10,
                            'shadowOffsetX': 0,
                            'shadowColor': 'rgba(0, 0, 0, 0.5)'
                        }
                    }
                }]
            }).classes('w-full h-64')
        
        self.machine_table = ui.table(
            columns=[
                {'name': 'select', 'label': '选择', 'field': 'select', 'align': 'center', 'style': 'width: 60px'},
                {'name': 'name', 'label': '名称', 'field': 'name', 'align': 'left'},
                {'name': 'host', 'label': '主机', 'field': 'host', 'align': 'left'},
                {'name': 'port', 'label': '端口', 'field': 'port', 'align': 'center'},
                {'name': 'platform', 'label': '平台', 'field': 'platform', 'align': 'center'},
                {'name': 'status', 'label': '状态', 'field': 'status', 'align': 'center'},
            ],
            rows=[],
            row_key='machine_id'
        ).classes('w-full')
        
        self.machine_table.add_slot('body-cell-select', '''
            <q-checkbox v-model="props.row.select" :val="props.row.machine_id" @update:model-value="(val) => $parent.$emit('rowSelect', props.row.machine_id, val)"></q-checkbox>
        ''')
        
        self.machine_table.add_slot('body-cell-status', '''
            <q-td :props="props">
                <div :class="props.row.status_class">{{ props.row.status }}</div>
            </q-td>
        ''')
        
        self.machine_table.on('rowSelect', self._on_row_select)
        
        with ui.row().classes('w-full mt-2 items-center'):
            ui.label('选中操作:').classes('mr-2')
            self.edit_btn = ui.button('编辑', icon='edit', color='primary', on_click=self._on_edit_machine).classes('mr-2')
            self.delete_btn = ui.button('删除', icon='delete', color='negative', on_click=self._on_delete_machine).classes('mr-2')
            self.test_btn = ui.button('测试连接', icon='wifi', color='positive', on_click=self._on_test_connection)
        
        self._refresh_machine_list()
    
    def _on_row_select(self, event_args):
        """行选择事件"""
        args = event_args.args
        logger.debug("[ROW SELECT DEBUG] event_args: %s, args type: %s, args value: %s", event_args, type(args), args)
        
        if isinstance(args, list) and len(args) > 0:
            machine_id = args[0]
            is_selected = args[1]
        else:
            machine_id = args
            is_selected = True
            
        # 更新选中的机器ID列表
        if is_selected and machine_id not in self._selected_machine_ids:
            self._selected_machine_ids.append(machine_id)
        elif not is_selected and machine_id in self._selected_machine_ids:
            self._selected_machine_ids.remove(machine_id)
        
        logger.debug("[ROW SELECT DEBUG] 当前选中的机器ID: %s", self._selected_machine_ids)
    
    def _on_edit_machine(self):
        """编辑机器按钮点击"""
        logger.debug("[EDIT DEBUG] _selected_machine_ids: %s", self._selected_machine_ids)
        if len(self._selected_machine_ids) != 1:
            ui.notify('编辑功能只能选择一个机器', type='warning')
            return
        
        machine_id = self._selected_machine_ids[0]
        logger.debug("[EDIT DEBUG] 准备编辑机器: %s", machine_id)
        self._show_edit_machine_dialog_by_id(machine_id)
    
    def _on_delete_machine(self):
        """删除机器按钮点击"""
        logger.debug("[DELETE DEBUG] 点击删除按钮, _selected_machine_ids: %s", self._selected_machine_ids)
        if not self._selected_machine_ids:
            ui.notify('请先选择要删除的机器', type='warning')
            return
        logger.debug("[DELETE DEBUG] 调用 _delete_machine 处理 %d 个机器", len(self._selected_machine_ids))
        self._delete_machine()
    
    def _on_test_connection(self):
        """测试连接按钮点击"""
        logger.debug("[TEST BTN DEBUG] _selected_machine_ids: %s", self._selected_machine_ids)
        if not self._selected_machine_ids:
            ui.notify('请先选择要测试连接的机器', type='warning')
            return
        if len(self._selected_machine_ids) != 1:
            ui.notify('连接测试只允许选择一个记录', type='warning')
            return
        logger.debug("[TEST BTN DEBUG] 准备测试连接: %s", self._selected_machine_ids[0])
        self._test_machine_connection(self._selected_machine_ids[0])
    
    def _refresh_machine_list(self):
        """刷新机器列表"""
        self._selected_machine_ids = []  # 清空选中的机器ID列表
        
        self._load_machines()
        
        # 统计机器状态
        online = 0
        offline = 0
        unknown = 0
        
        rows = []
        for machine in self._machines:
            status_text = "在线" if machine.status == "online" else ("离线" if machine.status == "offline" else "未知")
            platform_text = "Windows" if machine.platform == "windows" else "Linux"
            
            # 根据状态设置颜色
            if machine.status == "online":
                status_class = 'bg-green-100 text-green-800 rounded px-2 py-1'
                online += 1
            elif machine.status == "offline":
                status_class = 'bg-red-100 text-red-800 rounded px-2 py-1'
                offline += 1
            else:
                status_class = 'bg-yellow-100 text-yellow-800 rounded px-2 py-1'
                unknown += 1
            
            rows.append({
                'machine_id': machine.machine_id,
                'select': False,
                'name': machine.name,
                'host': f"{machine.host}:{machine.port}",
                'port': str(machine.port),
                'platform': platform_text,
                'status': status_text,
                'status_class': status_class
            })
        
        self.machine_table._props['rows'] = rows
        self.machine_table.update()
        
        # 更新饼图数据
        if self._machines:
            chart_data = [
                {'value': online, 'name': '在线'},
                {'value': offline, 'name': '离线'},
                {'value': unknown, 'name': '未知'}
            ]
            # 过滤掉数量为0的数据
            chart_data = [item for item in chart_data if item['value'] > 0]
        else:
            # 没有机器时显示友好提示
            chart_data = [{'value': 1, 'name': '暂无机器'}]
        
        self.machine_status_chart._props['options']['series'][0]['data'] = chart_data
        self.machine_status_chart.update()
        
        options = {}
        for m in self._machines:
            if m.status == "offline":
                options[m.machine_id] = f"⚠️ {m.name} ({m.host}) - 离线"
            else:
                options[m.machine_id] = f"{m.name} ({m.host})"
        
        self.machine_select.options = options
        if self._machines:
            first_machine_id = self._machines[0].machine_id
            self.machine_select.value = first_machine_id
    
    def _show_add_machine_dialog(self):
        """显示添加机器对话框"""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('添加机器').classes('text-lg font-bold mb-4')
            
            self.new_machine_name = ui.input(label='名称', placeholder='给机器起个名字').classes('w-full mb-2')
            self.new_machine_host = ui.input(label='主机IP', placeholder='例如: 192.168.1.100').classes('w-full mb-2')
            self.new_machine_port = ui.number(label='端口', value=22, min=1, max=65535).classes('w-full mb-2')
            
            def on_platform_change(e):
                if e.value == 'windows':
                    self.new_machine_port.set_value(settings.WINRM_HTTP_PORT)
                else:
                    self.new_machine_port.set_value(settings.SSH_PORT)
            
            self.new_machine_platform = ui.select(
                options={'linux': 'Linux (SSH)', 'windows': 'Windows (WinRM)'},
                label='平台',
                on_change=on_platform_change
            ).classes('w-full mb-2')
            self.new_machine_username = ui.input(label='用户名', placeholder='登录用户名').classes('w-full mb-2')
            self.new_machine_password = ui.input(label='密码', password=True).classes('w-full mb-2')
            self.new_machine_description = ui.textarea(label='描述', placeholder='可选').classes('w-full mb-4')
            
            with ui.row().classes('w-full justify-end'):
                ui.button('取消', on_click=dialog.close).classes('mr-2')
                ui.button('添加', on_click=lambda: self._add_machine(dialog)).classes('bg-primary')
        
        dialog.open()
    
    def _add_machine(self, dialog):
        """添加新机器"""
        name = self.new_machine_name.value.strip()
        host = self.new_machine_host.value.strip()
        port = int(self.new_machine_port.value)
        platform = self.new_machine_platform.value
        username = self.new_machine_username.value.strip()
        password = self.new_machine_password.value
        description = self.new_machine_description.value.strip()
        
        if not name:
            ui.notify('请填写机器名称', type='warning')
            return
        
        if not host:
            ui.notify('请填写主机IP', type='warning')
            return
        
        if not remote_machine_service.validate_host(host):
            ui.notify('主机IP格式不正确', type='warning')
            return
        
        if not port or port < 1 or port > 65535:
            ui.notify('端口号必须在1-65535之间', type='warning')
            return
        
        if not platform:
            ui.notify('请选择平台类型（Linux或Windows）', type='warning')
            return
        
        if not username:
            ui.notify('请填写用户名', type='warning')
            return
        
        if remote_machine_service.check_duplicate(host, port, username):
            ui.notify('该机器配置已存在（相同主机、端口和用户名）', type='warning')
            return
        
        try:
            success, message = remote_machine_service.add_machine(
                name=name,
                host=host,
                port=port,
                platform=platform,
                username=username,
                password=password,
                description=description
            )
            
            if success:
                ui.notify('机器添加成功', type='success')
                self._refresh_machine_list()
                dialog.close()
            else:
                ui.notify(f'添加失败: {message}', type='error')
        except Exception as e:
            ui.notify(f'添加失败: {str(e)}', type='error')
    
    def _show_edit_machine_dialog(self, machine: RemoteMachine):
        """显示编辑机器对话框"""
        with ui.dialog() as dialog, ui.card().classes('w-96'):
            ui.label('编辑机器').classes('text-lg font-bold mb-4')
            
            edit_name = ui.input(label='名称', value=machine.name).classes('w-full mb-2')
            edit_host = ui.input(label='主机IP', value=machine.host).classes('w-full mb-2')
            edit_port = ui.number(label='端口', value=machine.port, min=1, max=65535).classes('w-full mb-2')
            
            def on_edit_platform_change(e):
                if e.value == 'windows':
                    edit_port.set_value(settings.WINRM_HTTP_PORT)
                else:
                    edit_port.set_value(settings.SSH_PORT)
            
            edit_platform = ui.select(
                options={'linux': 'Linux (SSH)', 'windows': 'Windows (WinRM)'},
                label='平台',
                value=machine.platform,
                on_change=on_edit_platform_change
            ).classes('w-full mb-2')
            edit_username = ui.input(label='用户名', value=machine.username).classes('w-full mb-2')
            edit_password = ui.input(label='新密码', password=True, placeholder='留空则不修改').classes('w-full mb-2')
            edit_description = ui.textarea(label='描述', value=machine.description or '').classes('w-full mb-4')
            
            with ui.row().classes('w-full justify-end'):
                ui.button('取消', on_click=dialog.close).classes('mr-2')
                ui.button('保存', on_click=lambda: self._update_machine(dialog, machine.machine_id, edit_name.value, edit_host.value, int(edit_port.value), edit_platform.value, edit_username.value, edit_password.value, edit_description.value)).classes('bg-primary')
        
        dialog.open()
    
    def _update_machine(self, dialog, machine_id, name, host, port, platform, username, password, description):
        """更新机器配置"""
        if not name:
            ui.notify('请填写机器名称', type='warning')
            return
        
        if not host:
            ui.notify('请填写主机IP', type='warning')
            return
        
        if not remote_machine_service.validate_host(host):
            ui.notify('主机IP格式不正确', type='warning')
            return
        
        if not port or port < 1 or port > 65535:
            ui.notify('端口号必须在1-65535之间', type='warning')
            return
        
        if not platform:
            ui.notify('请选择平台类型（Linux或Windows）', type='warning')
            return
        
        if not username:
            ui.notify('请填写用户名', type='warning')
            return
        
        try:
            success, message = remote_machine_service.update_machine(
                machine_id=machine_id,
                name=name,
                host=host,
                port=port,
                platform=platform,
                username=username,
                password=password,
                description=description
            )
            
            if success:
                ui.notify('机器更新成功', type='success')
                self._refresh_machine_list()
                dialog.close()
            else:
                ui.notify(f'更新失败: {message}', type='error')
        except Exception as e:
            ui.notify(f'更新失败: {str(e)}', type='error')
    
    def _delete_machine(self):
        """删除机器（支持批量删除）"""
        if not self._selected_machine_ids:
            ui.notify('请先选择要删除的机器', type='warning')
            return
        
        # 获取选中的机器信息
        selected_machines = []
        for machine_id in self._selected_machine_ids:
            machine = remote_machine_service.get_machine(machine_id)
            if machine:
                selected_machines.append(machine)
        
        if not selected_machines:
            ui.notify('选中的机器不存在', type='warning')
            return
        
        with ui.dialog() as dialog, ui.card():
            if len(selected_machines) == 1:
                ui.label(f'确认删除机器 "{selected_machines[0].name}"?').classes('mb-4')
            else:
                ui.label(f'确认删除选中的 {len(selected_machines)} 台机器?').classes('mb-4')
                # 显示选中的机器列表
                with ui.card().classes('w-full mb-4'):
                    for machine in selected_machines:
                        ui.label(f'- {machine.name} ({machine.host})').classes('text-sm')
            
            ui.label('这将删除选中机器的所有配置信息。').classes('text-sm text-grey mb-4')
            
            with ui.row().classes('w-full justify-end'):
                ui.button('取消', on_click=dialog.close).classes('mr-2')
                ui.button('删除', on_click=lambda: self._confirm_delete_machine(dialog)).classes('bg-negative')
        
        dialog.open()
    
    def _confirm_delete_machine(self, dialog):
        """确认删除机器（支持批量删除）"""
        deleted_count = 0
        failed_count = 0
        
        for machine_id in self._selected_machine_ids:
            success, message = remote_machine_service.delete_machine(machine_id)
            if success:
                deleted_count += 1
            else:
                failed_count += 1
                logger.error("删除机器 %s 失败: %s", machine_id, message)
        
        if deleted_count > 0:
            if len(self._selected_machine_ids) == 1:
                ui.notify('机器删除成功', type='success')
            else:
                ui.notify(f'成功删除 {deleted_count} 台机器', type='success')
            self._refresh_machine_list()
        
        if failed_count > 0:
            ui.notify(f'删除失败 {failed_count} 台机器，请查看日志', type='error')
        
        dialog.close()
    
    def _test_machine_connection(self, machine_id: str):
        """测试机器连接"""
        import threading
        import time
        import logging
        
        logger = logging.getLogger('RemoteTestMonitor.TestMonitor')
        
        machine = remote_machine_service.get_machine(machine_id)
        if not machine:
            ui.notify('机器不存在', type='warning')
            return
        
        logger.info(f"[TEST BTN DEBUG] 开始测试连接")
        logger.info(f"[TEST BTN DEBUG] 机器ID: {machine_id}")
        logger.info(f"[TEST BTN DEBUG] 机器名称: {machine.name}")
        logger.info(f"[TEST BTN DEBUG] 平台类型: {machine.platform}")
        logger.info(f"[TEST BTN DEBUG] 主机地址: {machine.host}")
        logger.info(f"[TEST BTN DEBUG] 当前端口: {machine.port}")
        logger.info(f"[TEST BTN DEBUG] 期望端口 - Windows: {settings.WINRM_HTTP_PORT}/{settings.WINRM_HTTPS_PORT}, Linux: {settings.SSH_PORT}")
        
        # 检查平台和端口是否匹配
        platform_port_mismatch = False
        suggested_port = None
        
        if machine.platform == 'windows':
            logger.info(f"[TEST BTN DEBUG] Windows平台应该使用 WinRM 端口: {settings.WINRM_HTTP_PORT} 或 {settings.WINRM_HTTPS_PORT}")
            if machine.port not in [settings.WINRM_HTTP_PORT, settings.WINRM_HTTPS_PORT]:
                platform_port_mismatch = True
                suggested_port = settings.WINRM_HTTP_PORT
                logger.warning(f"[TEST BTN DEBUG] ⚠️ 端口错误! Windows机器使用了端口 {machine.port}, 应该使用 {settings.WINRM_HTTP_PORT} 或 {settings.WINRM_HTTPS_PORT}")
        else:
            logger.info(f"[TEST BTN DEBUG] Linux平台应该使用 SSH 端口: {settings.SSH_PORT}")
            if machine.port != settings.SSH_PORT:
                platform_port_mismatch = True
                suggested_port = settings.SSH_PORT
                logger.warning(f"[TEST BTN DEBUG] ⚠️ 端口错误! Linux机器使用了端口 {machine.port}, 应该使用 {settings.SSH_PORT}")
        
        # 如果平台和端口不匹配，提示用户并尝试使用正确的端口
        if platform_port_mismatch:
            original_port = machine.port
            try:
                logger.info(f"[TEST BTN DEBUG] 尝试使用正确的端口 {suggested_port} 进行连接测试")
                # 创建一个临时机器对象，使用正确的端口
                import copy
                temp_machine = copy.copy(machine)
                temp_machine.port = suggested_port
                
                # 先尝试使用正确的端口测试连接
                success, message = remote_machine_service.test_connection(temp_machine)
                if success:
                    logger.info(f"[TEST BTN DEBUG] 使用正确的端口 {suggested_port} 连接成功!")
                    ui.notify(f'⚠️ 检测到平台和端口不匹配，但使用正确的端口 {suggested_port} 连接成功。建议更新机器配置。', type='warning')
                    # 更新机器配置为正确的端口
                    remote_machine_service.update_machine(machine_id, port=suggested_port)
                    self._refresh_machine_list()
                    # 更新当前机器对象的端口
                    machine.port = suggested_port
            except Exception as e:
                logger.error(f"[TEST BTN DEBUG] 使用正确的端口 {suggested_port} 测试连接失败: {str(e)}")
        
        test_key = f"{machine_id}_{int(time.time() * 1000)}"
        
        self._test_key = test_key
        self._test_success = None
        self._test_message = None
        
        dialog = ui.dialog()
        status_label = None
        detail_label = None
        
        with dialog, ui.card().classes('w-96'):
            ui.label(f'连接测试 - {machine.name}').classes('text-lg font-bold mb-4')
            ui.label(f'主机: {machine.host}').classes('text-sm text-grey mb-2')
            ui.label(f'端口: {machine.port}').classes('text-sm text-grey mb-2')
            ui.label(f'平台: {"Linux (SSH)" if machine.platform == "linux" else "Windows (WinRM)"}').classes('text-sm text-grey mb-2')
            ui.separator()
            status_label = ui.label('正在建立连接...').classes('mb-2')
            detail_label = ui.label('').classes('text-sm text-grey mb-4')
            ui.separator()
            with ui.row().classes('w-full justify-end mt-2'):
                ui.button('关闭', on_click=dialog.close)
        
        dialog.open()
        
        def connection_test():
            success, message = remote_machine_service.test_connection(machine)
            self._test_success = success
            self._test_message = message
        
        def update_result():
            if self._test_key != test_key:
                return
            
            if self._test_success is None:
                return
            
            if hasattr(self, '_result_timer'):
                self._result_timer.deactivate()
                del self._result_timer
            
            if self._test_success:
                status_label.text = '✓ 连接成功'
                status_label.classes('text-positive font-bold mb-2')
                ui.notify(f'连接成功: {self._test_message}', type='success')
                remote_machine_service.update_machine_status(machine_id, 'online')
            else:
                status_label.text = '✗ 连接失败'
                status_label.classes('text-negative font-bold mb-2')
                ui.notify(f'连接失败: {self._test_message}', type='error')
                remote_machine_service.update_machine_status(machine_id, 'offline')
            
            detail_label.text = f'结果: {self._test_message}'
            self._refresh_machine_list()
        
        def check_result():
            if self._test_key != test_key:
                if hasattr(self, '_result_timer'):
                    self._result_timer.deactivate()
                    del self._result_timer
                return False
            
            if self._test_success is not None:
                update_result()
                if hasattr(self, '_result_timer'):
                    self._result_timer.deactivate()
                    del self._result_timer
                return False
            
            return True
        
        self._result_timer = ui.timer(0.3, check_result)
        
        threading.Thread(target=connection_test, daemon=True).start()
    
    def _on_execution_mode_change(self):
        """执行模式切换处理"""
        if self.execution_mode.value == '远程':
            self.machine_select_container.style('display: flex;')
            self.test_path_input.visible = False
            self.test_remote_path_input.style('display: block;')
        else:
            self.machine_select_container.style('display: none;')
            self.test_path_input.visible = True
            self.test_remote_path_input.style('display: none;')
    
    def _on_machine_select(self):
        """机器选择处理"""
        pass
    
    def _on_time_range_change(self, event=None):
        """时间范围选择变化处理"""
        self._refresh_test_statistics()
    
    def _refresh_test_statistics(self):
        """刷新测试执行统计数据"""
        time_range = self.time_range_select.value
        
        # 获取时间范围对应的秒数
        if time_range == '1h':
            seconds = 3600
        elif time_range == '24h':
            seconds = 86400
        elif time_range == '7d':
            seconds = 604800
        elif time_range == '30d':
            seconds = 2592000
        else:
            seconds = 86400  # 默认24小时
        
        import datetime
        
        # 计算时间范围
        current_time = datetime.datetime.now()
        start_time = current_time - datetime.timedelta(seconds=seconds)
        
        # 从数据库获取测试运行记录
        test_runs = storage_service.get_test_runs_by_time_range(start_time, current_time)
        logger.debug(f"[DEBUG] 获取到的测试运行记录数量: {len(test_runs)}")
        for run in test_runs:
            logger.debug(f"[DEBUG] 测试运行记录: run_id={run.run_id}, status={run.status}, start_time={run.start_time}, total_tests={run.total_tests}, passed_tests={run.passed_tests}")
        
        # 根据时间范围确定时间间隔
        if time_range == '1h':
            interval = datetime.timedelta(minutes=5)
            points = 12
        elif time_range == '24h':
            interval = datetime.timedelta(hours=1)
            points = 24
        elif time_range == '7d':
            interval = datetime.timedelta(hours=3)
            points = 56
        elif time_range == '30d':
            interval = datetime.timedelta(days=1)
            points = 30
        else:
            interval = datetime.timedelta(hours=1)
            points = 24
        
        # 初始化时间点和通过率数据
        time_points = []
        pass_rates = []
        
        # 如果有测试数据，直接使用每个测试的实际时间和通过率
        if test_runs:
            # 按测试开始时间排序
            sorted_test_runs = sorted(test_runs, key=lambda x: x.start_time)
            
            # 遍历测试运行记录，获取每个测试的实际时间和通过率
            for run in sorted_test_runs:
                # 跳过未完成的测试（只处理已完成、失败或停止的测试）
                if run.status not in ['completed', 'failed', 'stopped'] or run.total_tests == 0:
                    logger.debug(f"[DEBUG] 跳过测试 {run.run_id}: status={run.status}, total_tests={run.total_tests}")
                    continue
                
                # 计算当前测试的通过率
                test_pass_rate = (run.passed_tests / run.total_tests) * 100
                test_pass_rate = round(test_pass_rate, 2)
                logger.debug(f"[DEBUG] 测试 {run.run_id} 通过率: {test_pass_rate:.2f}%，执行时间: {run.start_time}")
                
                # 添加到时间点和通过率列表
                time_points.append(run.start_time)
                pass_rates.append(test_pass_rate)
        else:
            logger.debug(f"[DEBUG] 无测试数据")
        
        logger.debug(f"[DEBUG] 最终通过率数据: {pass_rates}")
        
        # 格式化时间点
        formatted_time_points = [tp.strftime('%Y-%m-%d %H:%M:%S') for tp in time_points]
        
        # 更新图表数据
        try:
            if hasattr(self, 'test_pass_rate_chart'):
                self.test_pass_rate_chart._props['options']['xAxis']['data'] = formatted_time_points
                self.test_pass_rate_chart._props['options']['series'][0]['data'] = pass_rates
                self.test_pass_rate_chart.update()
                logger.debug(f"[DEBUG] 图表数据更新成功")
            else:
                logger.error(f"[ERROR] test_pass_rate_chart 不存在")
        except Exception as e:
            logger.error(f"[ERROR] 更新图表数据失败: {e}")
    
    def _show_edit_machine_dialog_by_id(self, machine_id: str):
        """根据ID显示编辑机器对话框"""
        logger.debug("[EDIT DIALOG DEBUG] 获取机器信息，machine_id: %s", machine_id)
        machine = remote_machine_service.get_machine(machine_id)
        logger.debug("[EDIT DIALOG DEBUG] 获取结果: %s", machine)
        if machine:
            logger.debug("[EDIT DIALOG DEBUG] 准备打开编辑对话框，machine: %s", machine.name)
            self._show_edit_machine_dialog(machine)
        else:
            logger.error("[EDIT DIALOG DEBUG] 机器不存在")
            ui.notify('机器不存在或已被删除', type='error')
    
    def _start_test(self):
        """开始执行测试"""
        execution_mode = self.execution_mode.value
        
        if execution_mode == '远程':
            machine_id = self.machine_select.value
            if not machine_id:
                ui.notify('请选择远程机器', type='warning')
                return
            
            machine = remote_machine_service.get_machine(machine_id)
            if not machine:
                ui.notify('所选机器不存在', type='warning')
                return
            
            test_path = self.test_remote_path_input.value.strip()
            if not test_path:
                ui.notify('请输入远程测试路径', type='warning')
                return
            
            try:
                success, run_id = test_service.start_remote_test(machine_id, test_path)
                
                if success:
                    self.current_run_id = run_id
                    self._load_reports()
                    self.start_button.disable()
                    self.stop_button.enable()
                    self.test_status.text = f'测试正在远程执行: {machine.name} ({machine.host}) (Run ID: {run_id})'
                    self.test_status.classes(remove='text-red-500 text-green-500').classes('text-blue-500')
                    ui.notify(f'远程测试已启动: {machine.name}', type='success')
                else:
                    # 检查是否是路径不存在的错误
                    if '路径不存在' in run_id:
                        ui.notify(run_id, type='warning', duration=5)
                    else:
                        ui.notify(f'启动失败: {run_id}', type='error')
            except Exception as e:
                logger.error(f"远程测试启动异常: {e}")
                ui.notify(f'测试启动失败: {str(e)}', type='error')
        else:
            self._start_local_test()
    
    def _start_local_test(self):
        """开始本地测试"""
        raw_value = self.test_path_input.value
        logger.debug(f"原始输入值: '{raw_value}' (长度: {len(raw_value)})")
        logger.debug(f"字符编码: {[ord(c) for c in raw_value]}")
        
        test_path = self.test_path_input.value.strip()
        logger.debug(f"清理后路径: '{test_path}' (长度: {len(test_path)})")
        
        if not test_path:
            ui.notify('请输入测试路径', type='warning')
            logger.debug("路径为空，停止测试")
            return
        
        if not os.path.exists(test_path):
            ui.notify(f'路径不存在，请检查输入的路径是否正确:\n{test_path}', type='warning', duration=5)
            logger.warning(f"路径不存在: {test_path}")
            return
        
        if not os.path.isdir(test_path):
            ui.notify(f'路径指向的不是目录，请选择一个有效的测试目录:\n{test_path}', type='warning', duration=5)
            logger.warning(f"路径不是目录: {test_path}")
            return
        
        try:
            self.current_run_id = test_service.start_test(test_path)
            logger.debug(f"[DEBUG] 测试已启动: run_id={self.current_run_id}")
            logger.debug(f"[DEBUG] self.test_status 对象存在: {self.test_status is not None}")
            
            self._load_reports()
            
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
        
        def update_ui():
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
            # 尝试使用当前事件循环进行线程安全的UI更新
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(update_ui)
        except Exception as e:
            logger.error(f"使用事件循环更新UI失败: {e}")
            # 直接执行UI更新，NiceGUI内部应该会处理线程安全
            try:
                update_ui()
            except Exception as e:
                logger.error(f"直接执行UI更新失败: {e}")
    
    def _update_test_status(self, test_run: TestRun):
        """更新测试状态"""
        logger.debug(f"[STATUS-CB] _update_test_status 被调用: test_run.run_id={test_run.run_id}, self.current_run_id={self.current_run_id}, status={test_run.status}")
        
        # 无论current_run_id是否存在，只要是completed或failed状态都处理
        if test_run.status in ['completed', 'failed', 'stopped', 'running']:
            if not self.current_run_id:
                logger.debug(f"[STATUS-CB] current_run_id 为 None，自动设置为当前测试 run_id")
                self.current_run_id = test_run.run_id
        elif not self.current_run_id:
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
        elif test_run.status == 'running':
            self.test_status.text = f'测试正在执行 (Run ID: {test_run.run_id})'
            self.test_status.classes(remove='text-red-500 text-green-500').classes('text-blue-500')
            
            # 测试正在运行，确保开始按钮禁用，停止按钮启用
            self.start_button.disable()
            self.stop_button.enable()
            
            # 运行中状态也需要更新报告，以显示实时统计计数
            self._load_reports()
            return
        
        # 只有当测试状态不是 running 时，才更新按钮状态并清除 current_run_id
        self.start_button.enable()
        self.stop_button.disable()
        
        logger.info(f"[STATUS] 清除 current_run_id: {self.current_run_id}")
        self.current_run_id = None
        
        logger.info(f"[STATUS] 调用 _load_reports() 刷新UI")
        self._load_reports()
        logger.info(f"[STATUS] _load_reports() 执行完成")
        
        # 测试结束后自动刷新测试执行统计图表
        logger.info(f"[STATUS] 自动刷新测试执行统计图表")
        self._refresh_test_statistics()
        logger.info(f"[STATUS] 测试执行统计图表刷新完成")
    
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
    
    def _show_clear_confirm_dialog(self):
        """显示清空报告/日志的确认对话框"""
        from nicegui import ui
        
        def handle_confirm():
            dialog.close()
            self._clear_all_reports()
        
        with ui.dialog() as dialog, ui.card():
            ui.label('确认清空').classes('text-lg font-semibold mb-2')
            ui.label('此操作将清理掉所有报告和日志，且不可恢复，是否继续？')
            with ui.row().classes('w-full justify-end gap-2 mt-4'):
                ui.button('取消', on_click=dialog.close).props('flat')
                ui.button('确认', on_click=handle_confirm, color='red')
        
        dialog.open()
    
    def _clear_all_reports(self):
        """清空所有报告和日志"""
        logger.info("开始清空所有报告和日志")
        
        # 首先删除所有物理文件
        import os
        import glob
        
        # 获取报告和日志路径
        from config.settings import settings
        reports_path = settings.TEST_REPORTS_PATH
        logs_path = settings.LOG_PATH
        
        # 记录路径信息便于调试
        logger.debug(f"报告路径: {reports_path}")
        logger.debug(f"日志路径: {logs_path}")
        
        # 检查路径是否存在
        logger.debug(f"报告路径存在: {os.path.exists(reports_path)}")
        logger.debug(f"日志路径存在: {os.path.exists(logs_path)}")
        
        # 删除所有UUID风格的.html和.log文件（兼容Windows和Linux）
        def delete_uuid_files(paths, extension):
            deleted_count = 0
            
            # 确保paths是列表
            if not isinstance(paths, list):
                paths = [paths]
            
            for path in paths:
                if os.path.exists(path):
                    # UUID格式：xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
                    # 尝试多种模式以确保匹配所有可能的UUID文件
                    patterns = [
                        os.path.join(path, "*-*-*-*-*.{}".format(extension)),  # 标准UUID格式
                        os.path.join(path, "*.{}".format(extension)),  # 所有该类型文件（兜底）
                    ]
                    
                    deleted_files = set()
                    for pattern in patterns:
                        logger.debug(f"使用模式查找文件: {pattern}")
                        files_to_delete = glob.glob(pattern)
                        logger.debug(f"找到文件: {files_to_delete}")
                        for file_path in files_to_delete:
                            deleted_files.add(file_path)
                    
                    for file_path in deleted_files:
                        try:
                            # 只删除测试相关的UUID风格文件，不删除系统日志文件
                            file_name = os.path.basename(file_path)
                            logger.debug(f"检查文件: {file_name}")
                            if "app_" not in file_name and "system_" not in file_name:
                                os.remove(file_path)
                                deleted_count += 1
                                logger.debug(f"成功删除文件: {file_path}")
                            else:
                                logger.debug(f"保留系统日志文件: {file_path}")
                        except Exception as e:
                            logger.error(f"删除文件 {file_path} 失败: {e}")
            return deleted_count
        
        # 删除报告文件（.html）- 在两个路径中查找
        html_deleted = delete_uuid_files([reports_path, logs_path], "html")
        logger.info(f"✅ 成功删除 {html_deleted} 个HTML报告文件")
        
        # 删除日志文件（.log）- 在两个路径中查找
        log_deleted = delete_uuid_files([reports_path, logs_path], "log")
        logger.info(f"✅ 成功删除 {log_deleted} 个日志文件")
        
        # 然后删除数据库中的所有测试运行记录
        success = storage_service.delete_all_test_runs()
        if success:
            logger.info("✅ 成功清空所有数据库记录")
            
            # 清空UI中的报告卡片
            for run_id in list(self.report_cards.keys()):
                if 'card' in self.report_cards[run_id]:
                    self.report_cards[run_id]['card'].delete()
                del self.report_cards[run_id]
            
            # 清空日志输出
            self.log_output.clear()
            
            # 刷新报告列表
            self._load_reports()
            
            # 主动更新测试执行统计的趋势折线图
            if hasattr(self, '_refresh_test_statistics'):
                self._refresh_test_statistics()
            
            # 显示成功提示
            from nicegui import ui
            ui.notify(f'所有报告和日志已成功清空，共删除 {html_deleted} 个报告文件和 {log_deleted} 个日志文件', color='green')
        else:
            logger.error("❌ 清空报告和日志失败")
            from nicegui import ui
            ui.notify('清空报告和日志失败', color='red')
    
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
                'start_datetime': run.start_time,  # 用于排序
                'execution_type': run.execution_type,  # 本地/远程执行类型
                'node_name': run.node_name  # 执行机器名称
            })
        
        # 按状态和时间排序：运行中的排在最前面，其他按开始时间倒序
        reports.sort(key=lambda x: (x['status'] != 'running', -x['start_datetime'].timestamp()))
        
        current_report_ids = {r['run_id'] for r in reports}
        new_report_ids = current_report_ids - set(self.report_cards.keys())
        removed_report_ids = set(self.report_cards.keys()) - current_report_ids
        
        # 首先移除无报告提示（如果存在）
        if hasattr(self, 'no_reports_placeholder') and self.no_reports_placeholder is not None:
            self.no_reports_placeholder.delete()
            self.no_reports_placeholder = None
        
        if not reports:
            logger.info("没有报告数据，清空所有报告并显示提示")
            for run_id in list(self.report_cards.keys()):
                self.report_cards[run_id]['card'].delete()
                del self.report_cards[run_id]
            
            # 显示无报告提示
            from nicegui import ui
            with self.report_container:
                self.no_reports_placeholder = ui.column().classes('w-full py-12 text-center')
                with self.no_reports_placeholder:
                    ui.icon('file-text-outline').classes('text-gray-400 text-4xl mb-2')
                    ui.label('当前无任何测试报告和日志').classes('text-gray-500 text-lg')
                    ui.label('点击开始测试来生成您的第一份测试报告吧').classes('text-gray-400 text-sm mt-1')
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
                            
                            # 添加执行类型徽章
                            execution_type = report.get('execution_type', 'local')
                            node_name = report.get('node_name', 'localhost')
                            
                            if execution_type == 'remote':
                                execution_badge = ui.badge(f'远程执行: {node_name}', color='blue').props('ml-2')
                            else:
                                execution_badge = ui.badge('本地执行', color='green').props('ml-2')
                            
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
                        
                        with ui.row().classes('mt-3 w-full justify-start') as report_actions_row:
                            with ui.row().classes('flex-grow-0 gap-2'):
                                if report['report_path']:
                                    def create_view_handler(report_path, run_id):
                                        def view_handler():
                                            self._view_report(report_path, run_id)
                                        return view_handler
                                    
                                    view_button = ui.button(
                                        '查看报告',
                                        on_click=create_view_handler(report['report_path'], report['run_id']),
                                        color='primary',
                                        icon='article'
                                    ).props('flat rounded')
                                    no_report_label = None
                                else:
                                    view_button = None
                                    no_report_label = ui.label('无报告文件').classes('text-gray-400')
                                
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
                            
                            with ui.row().classes('flex-grow-0 gap-2'):
                                
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
                        'skipped_label': skipped_label,
                        'view_button': view_button,
                        'no_report_label': no_report_label,
                        'report_actions_row': report_actions_row
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
                old_data['duration'] != report['duration'] or
                old_data['report_path'] != report['report_path']
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
            
            # 更新报告相关UI
            if old_data['report_path'] != report['report_path']:
                logger.debug(f"[UPDATE] 报告路径变化: old={old_data['report_path']}, new={report['report_path']}")
                
                # 清除所有报告操作相关的UI组件
                # 直接清空整个report_actions_row容器
                card_info['report_actions_row'].clear()
                
                # 重新创建完整的报告操作按钮结构
                with card_info['report_actions_row']:
                    # 第一行：查看报告和下载日志按钮
                    with ui.row().classes('flex-grow-0 gap-2'):
                        if report['report_path']:
                            def create_view_handler(report_path, run_id):
                                def view_handler():
                                    self._view_report(report_path, run_id)
                                return view_handler
                            
                            card_info['view_button'] = ui.button(
                                '查看报告',
                                on_click=create_view_handler(report['report_path'], report['run_id']),
                                color='primary',
                                icon='article'
                            ).props('flat rounded')
                            card_info['no_report_label'] = None
                        else:
                            card_info['view_button'] = None
                            card_info['no_report_label'] = ui.label('无报告文件').classes('text-gray-400')
                        
                        # 重新创建下载日志按钮
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
                    
                    # 第二行：删除按钮
                    with ui.row().classes('flex-grow-0 gap-2'):
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
