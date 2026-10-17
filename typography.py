"""Load bundled typefaces once per Qt application, without system installation."""
from pathlib import Path
from PyQt6.QtGui import QFontDatabase, QGuiApplication


def load_fonts():
    app = QGuiApplication.instance()
    if app is None or app.property('subcontrol_fonts_loaded'):
        return
    directory = Path(__file__).resolve().parent/'assets'/'fonts'
    for filename in ('Manrope.ttf', 'GolosText.ttf'):
        QFontDatabase.addApplicationFont(str(directory/filename))
    app.setProperty('subcontrol_fonts_loaded', True)
