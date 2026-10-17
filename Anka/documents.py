from datetime import date
from html import escape
from pathlib import Path
from PyQt6.QtGui import QTextDocument
from PyQt6.QtPrintSupport import QPrinter


def write_pdf(path, title, columns, rows, footer=""):
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(path))
    printer.setDocName(title)
    headings = "".join(f"<th align='left'>{escape(str(c))}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    doc = QTextDocument()
    doc.setHtml(f"""<html><head><style>body{{font-family:'Segoe UI';font-size:11pt;color:#281e29;}}
        h1{{color:#a6255b;font-size:22pt;}}th{{background:#f7e5ee;padding:9px;}}
        td{{padding:9px;border-bottom:1px solid #eee;}}</style></head><body>
        <h1>SubControl</h1><h2>{escape(title)}</h2><p>Дата: {date.today():%d.%m.%Y}</p>
        <table width='100%' cellspacing='0' cellpadding='7'><thead><tr>{headings}</tr></thead>{body}</table>
        <p>{escape(footer)}</p><p style='color:#888'>Учебный проект. Документ не является фискальным чеком.</p></body></html>""")
    doc.print(printer)
    if not Path(path).is_file() or Path(path).stat().st_size == 0:
        raise OSError("PDF не удалось сохранить.")

