from nicegui import ui
from typing import Optional
from config.settings import settings

class Authentication:
    def __init__(self):
        self._authenticated = False
        self._username = None
    
    def is_authenticated(self) -> bool:
        """检查用户是否已认证"""
        return self._authenticated
    
    def get_username(self) -> Optional[str]:
        """获取当前用户名"""
        return self._username
    
    def login(self, username: str, password: str) -> bool:
        """用户登录"""
        if username == settings.USERNAME and password == settings.PASSWORD:
            self._authenticated = True
            self._username = username
            return True
        return False
    
    def logout(self):
        """用户登出"""
        self._authenticated = False
        self._username = None
    
    def require_auth(self, page):
        """需要认证的装饰器"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                if self.is_authenticated():
                    return func(*args, **kwargs)
                else:
                    # 显示登录界面
                    self._show_login_page(page)
            return wrapper
        return decorator
    
    def _show_login_page(self, page):
        """显示登录页面"""
        page.clear()
        
        with page:
            with ui.card().classes('w-96 mx-auto mt-20'):
                ui.label('远程测试监控系统').classes('text-xl font-bold mb-4 text-center')
                
                username_input = ui.input(label='用户名').classes('mb-2')
                password_input = ui.input(label='密码', password=True).classes('mb-4')
                
                error_label = ui.label('').classes('text-red-500 mb-2')
                
                def handle_login():
                    if self.login(username_input.value, password_input.value):
                        # 登录成功，刷新页面
                        page.reload()
                    else:
                        error_label.text = '用户名或密码错误'
                
                # 添加按回车键登录功能
                def on_enter_key(e):
                    if e.key == 'Enter':
                        handle_login()
                
                # 为用户名输入框添加回车键事件
                username_input.on('keydown.enter', on_enter_key)
                # 为密码输入框添加回车键事件
                password_input.on('keydown.enter', on_enter_key)
                
                ui.button('登录', on_click=handle_login).classes('w-full')

# 创建全局认证实例
auth = Authentication()
