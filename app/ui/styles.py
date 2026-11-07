from pathlib import Path
from PySide6.QtGui import QColor, QPalette


BACKGROUND_THEMES = {
    "mist": {"light": "#edf2f8", "dark": "#0f172a"},
    "sky": {"light": "#e8f3ff", "dark": "#10243b"},
    "aurora": {"light": "#eaf7f3", "dark": "#102b2b"},
    "graphite": {"light": "#e7e9ee", "dark": "#15171c"},
}

ACCENTS = {
    "blue": "#1769d2",
    "teal": "#087f8c",
    "violet": "#7048c6",
    "rose": "#c24168",
}


def build_palette(theme="light"):
    dark = str(theme).lower() == "dark"
    palette = QPalette()
    if dark:
        window, base, alternate, text = "#0f172a", "#111c2e", "#172235", "#f6f8fc"
        button, button_text, highlight, highlighted = "#1e293b", "#ffffff", "#1f4d83", "#ffffff"
        tooltip_base, tooltip_text = "#ffffff", "#111827"
    else:
        window, base, alternate, text = "#edf2f8", "#ffffff", "#f8fafd", "#111827"
        button, button_text, highlight, highlighted = "#ffffff", "#0b1220", "#dbeafe", "#0b1220"
        tooltip_base, tooltip_text = "#0b1220", "#ffffff"
    for group in (QPalette.Active, QPalette.Inactive):
        palette.setColor(group, QPalette.Window, QColor(window))
        palette.setColor(group, QPalette.Base, QColor(base))
        palette.setColor(group, QPalette.AlternateBase, QColor(alternate))
        palette.setColor(group, QPalette.Text, QColor(text))
        palette.setColor(group, QPalette.WindowText, QColor(text))
        palette.setColor(group, QPalette.Button, QColor(button))
        palette.setColor(group, QPalette.ButtonText, QColor(button_text))
        palette.setColor(group, QPalette.Highlight, QColor(highlight))
        palette.setColor(group, QPalette.HighlightedText, QColor(highlighted))
        palette.setColor(group, QPalette.ToolTipBase, QColor(tooltip_base))
        palette.setColor(group, QPalette.ToolTipText, QColor(tooltip_text))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#7c8798"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#7c8798"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#7c8798"))
    return palette


def _file_url(path):
    if not path:
        return ""
    return Path(path).resolve().as_uri().replace('"', "\\\"")


def build_app_qss(
    theme="light",
    glass="light",
    text_style="Segoe UI Variable",
    background="mist",
    accent="blue",
    compact_nav=False,
    custom_background="",
):
    dark = str(theme).lower() == "dark"
    mode = "dark" if dark else "light"
    accent_color = ACCENTS.get(str(accent).lower(), ACCENTS["blue"])
    page_background = BACKGROUND_THEMES.get(str(background).lower(), BACKGROUND_THEMES["mist"])[mode]
    dense = str(glass).lower() == "dense"

    if dark:
        text = "#f6f8fc"
        strong = "#ffffff"
        muted = "#c1ccdc"
        shell = "rgba(15,23,42,214)"
        sidebar = "rgba(21,31,48,252)" if dense else "rgba(21,31,48,228)"
        card = "rgba(30,41,59,252)" if dense else "rgba(30,41,59,224)"
        input_bg = "rgba(15,23,42,245)"
        border = "rgba(148,163,184,82)"
        button_bg = "rgba(30,41,59,245)"
        hover = "rgba(59,130,246,68)"
        selected = "#1f4d83"
        selected_border = "#3979bd"
        table_header = "#1e293b"
        table_alt = "#172235"
        progress_bg = "#26364d"
    else:
        text = "#111827"
        strong = "#0b1220"
        muted = "#111827"
        shell = "rgba(238,243,249,228)"
        sidebar = "rgba(250,252,255,252)" if dense else "rgba(250,252,255,238)"
        card = "rgba(255,255,255,252)" if dense else "rgba(255,255,255,224)"
        input_bg = "rgba(255,255,255,245)"
        border = "#d5deea"
        button_bg = "rgba(255,255,255,235)"
        hover = "rgba(222,235,251,190)"
        selected = "#e3efff"
        selected_border = "#c5ddfb"
        table_header = "#f5f8fc"
        table_alt = "#f8fafd"
        progress_bg = "#e2eaf4"

    nav_padding = "7px 10px" if compact_nav else "9px 11px"
    family = str(text_style or "Segoe UI Variable").replace('"', "")
    if custom_background:
        image_url = _file_url(custom_background)
        window_background = (
            f'background-color: {page_background}; background-image: url("{image_url}"); '
            "background-repeat: no-repeat; background-position: center;"
        )
    else:
        window_background = f"background: {page_background};"

    return f"""
* {{ font-family: "{family}"; }}
QWidget {{ color: {text}; font-size: 10pt; }}
QMainWindow {{ {window_background} }}
QDialog, QMessageBox, QFileDialog {{ background: {card}; color: {text}; }}
QDialog QLabel, QMessageBox QLabel, QFileDialog QLabel {{ color: {strong}; }}
QDialog QPushButton, QMessageBox QPushButton, QFileDialog QPushButton {{ color: {strong}; }}
QWidget#PageSurface, QWidget#SettingsContent, QWidget#WorkspaceContent, QStackedWidget {{ background: transparent; }}
QFrame#Shell {{ background: {shell}; }}
QFrame#Sidebar {{
  background: {sidebar}; border: 1px solid {border}; border-radius: 18px;
}}
QFrame#MainPanel {{ background: transparent; }}
QFrame#GlassCard {{
  background: {card}; border: 1px solid {border}; border-radius: 16px;
}}
QLabel#Brand {{ font-size: 17pt; font-weight: 700; color: {strong}; }}
QLabel#Eyebrow {{ color: {strong}; font-size: 9pt; font-weight: 700; }}
QLabel#PageTitle {{ font-size: 25pt; font-weight: 700; color: {strong}; }}
QLabel#SubTitle {{ color: {muted}; font-size: 10pt; }}
QLabel#SectionTitle {{ font-size: 12pt; font-weight: 700; color: {strong}; }}
QLabel#NavGroup {{ color: {strong}; font-size: 9.5pt; font-weight: 800; padding: 12px 10px 4px 10px; }}
QLabel#DropGlyph {{ font-size: 30pt; color: {accent_color}; font-weight: 300; }}
QLabel#DropHeadline {{ font-size: 16pt; font-weight: 700; color: {strong}; }}
QPushButton {{
  background: {button_bg}; border: 1px solid {border}; border-radius: 9px;
  padding: 9px 14px; color: {strong}; font-weight: 600;
}}
QPushButton:hover {{ background: {hover}; border-color: {accent_color}; }}
QPushButton:pressed {{ background: {selected}; }}
QPushButton#Primary {{
  color: white; font-weight: 700; border: 1px solid {accent_color};
  background: {accent_color}; padding: 11px 19px;
}}
QPushButton#Primary:hover {{ background: {accent_color}; border-color: {accent_color}; }}
QPushButton#Nav {{
  text-align: left; background: transparent; border: 1px solid transparent;
  padding: {nav_padding}; color: {strong}; font-weight: 650;
}}
QPushButton#Nav:hover {{ background: {hover}; }}
QPushButton#Nav:checked {{
  background: {selected}; border: 1px solid {selected_border};
  color: {strong}; font-weight: 750;
}}
QPushButton#NavSub {{
  text-align: left; background: transparent; border: 1px solid transparent;
  padding: 6px 8px 6px 16px; color: {muted}; font-size: 9pt; font-weight: 600;
}}
QPushButton#NavSub:hover {{ background: {hover}; border-color: {accent_color}; color: {strong}; }}
QToolButton#SettingsButton {{
  background: {button_bg}; border: 1px solid {border}; border-radius: 9px;
  color: {strong}; font-size: 17pt; font-weight: 700; padding: 2px;
}}
QToolButton#SettingsButton:hover {{ background: {hover}; border-color: {accent_color}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget, QListWidget {{
  background: {input_bg}; border: 1px solid {border}; border-radius: 9px;
  padding: 8px; selection-background-color: {selected}; color: {strong};
}}
QComboBox::drop-down {{ border: 0; width: 25px; }}
QSlider::groove:horizontal {{ height: 6px; background: {progress_bg}; border-radius: 3px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; border-radius: 7px; background: {accent_color}; }}
QTableWidget {{ gridline-color: {border}; alternate-background-color: {table_alt}; }}
QHeaderView::section {{
  background: {table_header}; border: 0; border-bottom: 1px solid {border};
  padding: 10px; color: {strong}; font-weight: 700;
}}
QProgressBar {{ background: {progress_bg}; border: 0; border-radius: 5px; height: 9px; }}
QProgressBar::chunk {{ background: {accent_color}; border-radius: 5px; }}
QStatusBar {{ background: transparent; color: {muted}; }}
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea#NavScroll {{ background: transparent; border: 0; }}
QScrollArea#NavScroll QWidget#NavContent {{ background: transparent; }}
QScrollArea#NavScroll QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QScrollArea#SettingsScroll {{ background: transparent; border: 0; }}
QScrollArea#SettingsScroll QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QScrollArea#WorkspaceScroll QWidget#qt_scrollarea_viewport {{ background: transparent; }}
QFrame#DropZone {{
  background: {card}; border: 1px dashed {accent_color}; border-radius: 16px;
}}
QFrame#StatCard {{ background: {card}; border: 1px solid {border}; border-radius: 13px; }}
QLabel#StatValue {{ color: {strong}; font-size: 18pt; font-weight: 750; }}
QListWidget#RecentList {{ background: transparent; border: 0; }}
QTableWidget#QueueTable {{ background: {input_bg}; }}
QToolTip {{ background: {strong}; color: {page_background}; border: 1px solid {border}; }}
QCheckBox {{ color: {strong}; spacing: 8px; font-weight: 600; }}
QLabel#SettingHint {{ color: {muted}; }}
QLabel#PreviewImage {{ background: {input_bg}; border: 1px solid {border}; border-radius: 10px; color: {muted}; padding: 8px; }}
QVideoWidget#VideoPreview {{ background: #090d14; border: 1px solid {border}; border-radius: 10px; }}
QLabel#PrivacyLabel {{ color: {strong}; font-weight: 700; }}
"""


APP_QSS = build_app_qss()
