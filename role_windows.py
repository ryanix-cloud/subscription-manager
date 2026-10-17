from datetime import date

import matplotlib
from PyQt6 import uic
from PyQt6.QtCore import Qt, QTimer, QEvent, QSize
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QGridLayout, QGroupBox, QMessageBox, QMenu, QFrame, QFileDialog, QLineEdit,
    QSystemTrayIcon, QStyle, QSizePolicy,
)
from database import (get_admin_summary, get_admin_subscription_status_stats, get_admin_monthly_payment_stats,
                      get_user_dashboard_summary, get_user_subscriptions, get_all_subscription_plans,
                      get_user_plan_ids, add_user_subscription, _fetch_all, cancel_user_subscription,
                      get_user_payments, get_user_notifications, mark_user_notifications_read,
                      create_user_notification, get_user_settings, update_user_profile,
                      update_user_password, update_notifications_setting, process_due_payments,
                      ensure_receipts_for_successful_payments)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
import os
import webbrowser
from pathlib import Path
matplotlib.rcParams['font.family'] = ['DejaVu Sans']

from user_window import UserWindow

class ManagerWindow(QMainWindow):

    def __init__(self, user):
        super().__init__()
        self.setWindowTitle('Окно менеджера')
        self.resize(900, 600)
        label = QLabel(f"Добро пожаловать, {user['user_name']}!\nЗдесь будет просмотр подписок и отчётов.")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(label)

class AdminWindow(QMainWindow):

    def __init__(self, user):
        super().__init__()
        self.setWindowTitle('Панель администратора')
        self.resize(1000, 700)
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)
        title = QLabel(f"Панель администратора — {user['user_name']}")
        title.setStyleSheet('font-size: 22px; font-weight: bold;')
        main_layout.addWidget(title)
        cards_layout = QGridLayout()
        cards_layout.setSpacing(12)
        self.users_card = self.create_card('Пользователи')
        self.subscriptions_card = self.create_card('Подписки')
        self.success_card = self.create_card('Успешные платежи')
        self.failed_card = self.create_card('Неуспешные платежи')
        cards_layout.addWidget(self.users_card, 0, 0)
        cards_layout.addWidget(self.subscriptions_card, 0, 1)
        cards_layout.addWidget(self.success_card, 1, 0)
        cards_layout.addWidget(self.failed_card, 1, 1)
        main_layout.addLayout(cards_layout)
        status_group = QGroupBox('Подписки по статусам')
        status_layout = QVBoxLayout(status_group)
        self.status_canvas = FigureCanvasQTAgg(Figure(figsize=(5, 3)))
        status_layout.addWidget(self.status_canvas)
        main_layout.addWidget(status_group)
        payments_group = QGroupBox('Успешные платежи за последние шесть месяцев')
        payments_layout = QVBoxLayout(payments_group)
        self.payments_canvas = FigureCanvasQTAgg(Figure(figsize=(5, 3)))
        payments_layout.addWidget(self.payments_canvas)
        main_layout.addWidget(payments_group)
        buttons_layout = QHBoxLayout()
        refresh_button = QPushButton('Обновить статистику')
        refresh_button.clicked.connect(self.load_statistics)
        export_button = QPushButton('Экспорт в PDF')
        export_button.clicked.connect(self.export_pdf)
        buttons_layout.addWidget(refresh_button)
        buttons_layout.addWidget(export_button)
        buttons_layout.addStretch()
        main_layout.addLayout(buttons_layout)
        self.load_statistics()

    def create_card(self, title):
        card = QGroupBox(title)
        layout = QVBoxLayout(card)
        value_label = QLabel('—')
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setStyleSheet('font-size: 24px; font-weight: bold; padding: 8px;')
        layout.addWidget(value_label)
        card.value_label = value_label
        return card

    def load_statistics(self):
        try:
            summary = get_admin_summary() or {}
            self.users_card.value_label.setText(str(summary.get('users_count', 0)))
            self.subscriptions_card.value_label.setText(str(summary.get('subscriptions_count', 0)))
            self.success_card.value_label.setText(str(summary.get('successful_payments_count', 0)))
            self.failed_card.value_label.setText(str(summary.get('failed_payments_count', 0)))
            status_stats = get_admin_subscription_status_stats()
            status_labels = [item['status'] for item in status_stats]
            status_values = [int(item['subscription_count']) for item in status_stats]
            figure = self.status_canvas.figure
            figure.clear()
            ax = figure.add_subplot(111)
            if sum(status_values) > 0:
                ax.pie(status_values, labels=status_labels, autopct='%1.1f%%', startangle=90)
                ax.axis('equal')
            else:
                ax.text(0.5, 0.5, 'Нет данных о подписках', ha='center', va='center')
                ax.axis('off')
            figure.tight_layout()
            self.status_canvas.draw()
            monthly_stats = get_admin_monthly_payment_stats()
            months = [item['month'] for item in monthly_stats]
            amounts = [float(item['total_amount'] or 0) for item in monthly_stats]
            figure = self.payments_canvas.figure
            figure.clear()
            ax = figure.add_subplot(111)
            if months:
                ax.bar(months, amounts)
                ax.set_ylabel('Сумма, ₽')
                ax.set_xlabel('Месяц')
                ax.tick_params(axis='x', rotation=35)
            else:
                ax.text(0.5, 0.5, 'Нет данных о платежах', ha='center', va='center')
                ax.axis('off')
            figure.tight_layout()
            self.payments_canvas.draw()
        except Exception as error:
            QMessageBox.critical(self, 'Ошибка загрузки', f'Не удалось загрузить статистику:\n{error}')

    def export_pdf(self):
        file_path, _ = QFileDialog.getSaveFileName(self, 'Сохранить отчёт', 'admin_report.pdf', 'PDF-файлы (*.pdf)')
        if not file_path:
            return
        if not file_path.lower().endswith('.pdf'):
            file_path += '.pdf'
        try:
            self.load_statistics()
            summary = get_admin_summary() or {}
            with PdfPages(file_path) as pdf:
                summary_figure = Figure(figsize=(8.27, 11.69))
                ax = summary_figure.add_subplot(111)
                ax.axis('off')
                ax.text(0.5, 0.92, 'Отчёт администратора', ha='center', fontsize=18, fontweight='bold')
                lines = [
                    f"Дата формирования: {date.today():%d.%m.%Y}", '',
                    f"Пользователей: {summary.get('users_count', 0)}",
                    f"Подписок: {summary.get('subscriptions_count', 0)}",
                    f"Успешных платежей: {summary.get('successful_payments_count', 0)}",
                    f"Неуспешных платежей: {summary.get('failed_payments_count', 0)}",
                ]
                ax.text(0.12, 0.78, '\n'.join(lines), ha='left', va='top', fontsize=13, linespacing=1.8)
                pdf.savefig(summary_figure, bbox_inches='tight')
                pdf.savefig(self.status_canvas.figure, bbox_inches='tight')
                pdf.savefig(self.payments_canvas.figure, bbox_inches='tight')
            QMessageBox.information(self, 'Экспорт завершён', f'Отчёт сохранён:\n{file_path}')
        except Exception as error:
            QMessageBox.critical(self, 'Ошибка экспорта', f'Не удалось создать PDF:\n{error}')
