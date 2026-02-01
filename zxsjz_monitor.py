import sys
import json
import time
import random
import requests
from threading import Thread, Event
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QGroupBox, QMessageBox,
    QSpinBox, QDoubleSpinBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont, QIcon
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

# 配置文件路径（保存SCKEY和历史价格）
CONFIG_FILE = "price_monitor_config.json"
# ========== 新增：固定你的监控URL ==========
FIXED_MONITOR_URL = "https://zxfps.com/"  # 改成你的目标URL，用户无法修改
# ==========================================

# 监控线程类（独立线程，避免界面卡死）
class MonitorThread(QThread):
    log_signal = pyqtSignal(str)  # 日志信号
    notify_signal = pyqtSignal(list, float, int)  # 通知信号
    finish_signal = pyqtSignal()  # 结束信号

    def __init__(self, threshold, sckey, refresh_interval, max_refresh):
        super().__init__()
        self.url = FIXED_MONITOR_URL  # 使用固定URL
        self.threshold = threshold
        self.sckey = sckey
        self.refresh_interval = refresh_interval
        self.max_refresh = max_refresh
        self.is_paused = Event()
        self.is_stopped = Event()
        self.driver = None

    def pause(self):
        """暂停监控"""
        self.is_paused.set()
        self.log_signal.emit("⚠️ 监控已暂停")

    def resume(self):
        """恢复监控"""
        self.is_paused.clear()
        self.log_signal.emit("▶️ 监控已恢复")

    def stop(self):
        """停止监控"""
        self.is_stopped.set()
        self.is_paused.clear()
        self.log_signal.emit("🛑 正在停止监控...")

    def click_price_asc(self):
        """模拟点击价格升序"""
        try:
            price_header = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "el-table_1_column_19"))
            )
            price_header.click()
            time.sleep(0.5)
            price_header.click()
            time.sleep(2)
            self.log_signal.emit("✅ 已触发价格升序排序")
        except Exception as e:
            self.log_signal.emit(f"⚠️ 点击升序失败：{str(e)}")

    def send_serverchan_notify(self, price_list, threshold, refresh_count):
        """发送Server酱通知"""
        if not self.sckey:
            self.log_signal.emit("⚠️ 未配置SCKEY，跳过微信通知")
            return
        try:
            title = f"🎉 找到低于{threshold:.2f}元的价格！"
            content = f"""### 价格监控提醒
- 筛选阈值：{threshold:.2f} 元
- 符合条件数量：{len(price_list)} 个
- 价格列表：
"""
            for idx, price in enumerate(price_list, 1):
                content += f"  {idx}. {price:.2f} 元\n"
            content += f"\n监控页面：{self.url}\n刷新次数：{refresh_count} 次"

            url = f"https://sctapi.ftqq.com/{self.sckey}.send"
            response = requests.post(url, data={"title": title, "desp": content}, timeout=15)
            response.raise_for_status()
            result = response.json()
            
            if result.get("code") == 0:
                self.log_signal.emit("✅ 微信通知发送成功！")
            else:
                self.log_signal.emit(f"❌ 通知发送失败：{result.get('msg')}")
        except Exception as e:
            self.log_signal.emit(f"❌ 通知发送异常：{str(e)}")

    def run(self):
        """线程主逻辑"""
        # 初始化浏览器
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-images")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(10)
            self.log_signal.emit("✅ 浏览器启动成功")
        except Exception as e:
            self.log_signal.emit(f"❌ 浏览器启动失败：{str(e)}")
            self.finish_signal.emit()
            return

        refresh_count = 0
        found = False

        while refresh_count < self.max_refresh and not self.is_stopped.is_set():
            # 检查暂停状态
            if self.is_paused.is_set():
                time.sleep(1)
                continue

            refresh_count += 1
            self.log_signal.emit(f"\n【第 {refresh_count} 次刷新】开始监控...")

            try:
                # 加载页面
                self.driver.get(self.url)
                self.log_signal.emit("✅ 页面加载完成")

                # 触发升序排序
                self.click_price_asc()

                # 提取价格
                price_cells = self.driver.find_elements(By.CSS_SELECTOR, "td.el-table_1_column_19.is-center")
                valid_prices = []

                for cell in price_cells:
                    try:
                        price_text = cell.text.strip()
                        if price_text and price_text.replace(".", "").isdigit():
                            price = float(price_text)
                            if price < self.threshold:
                                valid_prices.append(price)
                    except:
                        continue

                # 检查结果
                if valid_prices:
                    self.log_signal.emit(f"🎉 找到 {len(valid_prices)} 个符合条件的价格：{[f'{p:.2f}' for p in valid_prices]}")
                    self.send_serverchan_notify(valid_prices, self.threshold, refresh_count)
                    found = True
                    break
                else:
                    self.log_signal.emit(f"❌ 未找到低于 {self.threshold:.2f} 元的价格")
                    # 等待刷新间隔
                    for _ in range(self.refresh_interval):
                        if self.is_stopped.is_set() or self.is_paused.is_set():
                            break
                        time.sleep(1)

            except Exception as e:
                self.log_signal.emit(f"⚠️ 刷新出错：{str(e)}")
                time.sleep(self.refresh_interval)

        # 清理资源
        if self.driver:
            self.driver.quit()
        self.log_signal.emit("\n======================================")
        if found:
            self.log_signal.emit("✅ 监控完成：找到符合条件的价格！")
        elif self.is_stopped.is_set():
            self.log_signal.emit("🛑 监控已手动停止")
        else:
            self.log_signal.emit(f"❌ 监控完成：刷新 {self.max_refresh} 次未找到符合条件的价格")
        
        self.finish_signal.emit()

# 主窗口类
class PriceMonitorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Astoom - 准星找号+公众号通知")
        self.setGeometry(100, 100, 800, 600)
        self.setMinimumSize(700, 500)
        self.setWindowIcon(QIcon("zx.ico"))

        # 初始化变量
        self.monitor_thread = None
        self.config = self.load_config()

        # 创建UI
        self.init_ui()

    def load_config(self):
        """加载配置文件"""
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"sckey": "", "last_threshold": 0.0}

    def save_config(self):
        """保存配置文件"""
        self.config["sckey"] = self.sckey_input.text().strip()
        self.config["last_threshold"] = self.threshold_input.value()
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"保存配置失败：{str(e)}")

    def init_ui(self):
        """初始化界面"""
        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 1. 基础配置组
        config_group = QGroupBox("基础配置")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(10)

        # ========== 核心改动1：URL改为只读，固定显示 ==========
        url_layout = QHBoxLayout()
        url_label = QLabel("监控URL：")
        url_label.setFont(QFont("Arial", 10))
        self.url_input = QLineEdit()
        self.url_input.setText(FIXED_MONITOR_URL)  # 固定显示你的URL
        self.url_input.setReadOnly(True)  # 设置为只读，用户无法修改
        self.url_input.setStyleSheet("background-color: #F0F0F0;")  # 灰色背景，提示不可修改
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        config_layout.addLayout(url_layout)
        # =====================================================

        # 价格阈值配置
        threshold_layout = QHBoxLayout()
        threshold_label = QLabel("价格阈值：")
        threshold_label.setFont(QFont("Arial", 10))
        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0.01, 999999.99)
        self.threshold_input.setDecimals(2)
        self.threshold_input.setValue(self.config.get("last_threshold", 100.0))
        self.threshold_input.setPrefix("¥ ")
        threshold_layout.addWidget(threshold_label)
        threshold_layout.addWidget(self.threshold_input)
        config_layout.addLayout(threshold_layout)

        # Server酱SCKEY配置
        sckey_layout = QHBoxLayout()
        sckey_label = QLabel("Server酱SCKEY：")
        sckey_label.setFont(QFont("Arial", 10))
        self.sckey_input = QLineEdit()
        self.sckey_input.setPlaceholderText("选填 - 输入后自动保存，留空则不发送微信通知")
        self.sckey_input.setText(self.config.get("sckey", ""))
        sckey_layout.addWidget(sckey_label)
        sckey_layout.addWidget(self.sckey_input)
        config_layout.addLayout(sckey_layout)

        # 刷新配置
        refresh_layout = QHBoxLayout()
        refresh_interval_label = QLabel("刷新间隔（秒）：")
        refresh_interval_label.setFont(QFont("Arial", 10))
        self.refresh_interval_input = QSpinBox()
        self.refresh_interval_input.setRange(3, 60)
        self.refresh_interval_input.setValue(5)

        max_refresh_label = QLabel("最大刷新次数：")
        max_refresh_label.setFont(QFont("Arial", 10))
        self.max_refresh_input = QSpinBox()
        self.max_refresh_input.setRange(1, 999)
        self.max_refresh_input.setValue(100)

        refresh_layout.addWidget(refresh_interval_label)
        refresh_layout.addWidget(self.refresh_interval_input)
        refresh_layout.addSpacing(20)
        refresh_layout.addWidget(max_refresh_label)
        refresh_layout.addWidget(self.max_refresh_input)
        config_layout.addLayout(refresh_layout)

        main_layout.addWidget(config_group)

        # 2. 控制按钮组
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.start_btn = QPushButton("开始监控")
        self.start_btn.setFont(QFont("Arial", 10, QFont.Bold))
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px; border-radius: 4px;")
        self.start_btn.clicked.connect(self.start_monitor)

        self.pause_btn = QPushButton("暂停监控")
        self.pause_btn.setFont(QFont("Arial", 10))
        self.pause_btn.setStyleSheet("background-color: #FFC107; color: black; padding: 8px; border-radius: 4px;")
        self.pause_btn.clicked.connect(self.pause_monitor)
        self.pause_btn.setEnabled(False)

        self.stop_btn = QPushButton("停止监控")
        self.stop_btn.setFont(QFont("Arial", 10))
        self.stop_btn.setStyleSheet("background-color: #F44336; color: white; padding: 8px; border-radius: 4px;")
        self.stop_btn.clicked.connect(self.stop_monitor)
        self.stop_btn.setEnabled(False)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.pause_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # 3. 日志输出组
        log_group = QGroupBox("监控日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("background-color: #F8F8F8; border: 1px solid #DDD;")
        log_layout.addWidget(self.log_text)
        main_layout.addWidget(log_group)

    def append_log(self, text):
        """追加日志"""
        self.log_text.append(text)
        # 自动滚动到底部
        self.log_text.moveCursor(self.log_text.textCursor().End)

    def start_monitor(self):
        """开始监控"""
        # 保存配置
        self.save_config()

        threshold = self.threshold_input.value()
        sckey = self.sckey_input.text().strip()
        refresh_interval = self.refresh_interval_input.value()
        max_refresh = self.max_refresh_input.value()

        # 禁用开始按钮，启用暂停/停止
        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

        # 清空日志
        self.log_text.clear()
        self.append_log("🚀 准备启动监控...")
        self.append_log(f"📌 监控URL：{FIXED_MONITOR_URL}")  # 显示固定URL
        self.append_log(f"💰 价格阈值：¥ {threshold:.2f}")
        self.append_log(f"🔄 刷新间隔：{refresh_interval}秒 | 最大刷新次数：{max_refresh}次")
        if sckey:
            self.append_log(f"📢 已配置SCKEY，将发送微信通知")
        else:
            self.append_log(f"📢 未配置SCKEY，不发送微信通知")

        # ========== 核心改动2：启动线程时不再传URL ==========
        self.monitor_thread = MonitorThread(
            threshold=threshold,
            sckey=sckey,
            refresh_interval=refresh_interval,
            max_refresh=max_refresh
        )
        self.monitor_thread.log_signal.connect(self.append_log)
        self.monitor_thread.finish_signal.connect(self.monitor_finished)
        self.monitor_thread.start()

    def pause_monitor(self):
        """暂停监控"""
        if self.monitor_thread and self.monitor_thread.isRunning():
            if self.pause_btn.text() == "暂停监控":
                self.monitor_thread.pause()
                self.pause_btn.setText("恢复监控")
            else:
                self.monitor_thread.resume()
                self.pause_btn.setText("暂停监控")

    def stop_monitor(self):
        """停止监控"""
        if self.monitor_thread and self.monitor_thread.isRunning():
            self.monitor_thread.stop()
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)

    def monitor_finished(self):
        """监控结束回调"""
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setText("暂停监控")

# 程序入口
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", 10))
    window = PriceMonitorWindow()
    window.show()
    sys.exit(app.exec_())