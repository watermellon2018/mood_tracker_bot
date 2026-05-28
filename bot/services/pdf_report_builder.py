"""PDF-отчёт через reportlab Platypus.

Builder получает ReportData (см. report_data_service.py), создаёт временные
PNG через report_charts, собирает PDF. После build все временные PNG
удаляются вызывающим (handlers/reports.py).

Reportlab Platypus — это поточный layout: списки Flowable объединяются в
SimpleDocTemplate, который автоматически разбивает на страницы. Это
проще, чем работать с canvas координатами.

Шрифты: используем встроенный Helvetica + DejaVuSans для кириллицы. Если
DejaVuSans недоступен — фолбэк на Helvetica с латиницей.
"""
from __future__ import annotations

import logging
import os
import time as _time
from collections import Counter
from datetime import date
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from bot.constants_questions import QUESTION_DEFINITIONS
from bot.services import report_charts
from bot.services.report_data_service import (
    CustomStats,
    OptionalStats,
    ReportData,
)
from bot.utils.date_periods import PERIOD_LABELS

logger = logging.getLogger(__name__)


# ---------- font setup ----------

_FONT_NORMAL = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_DEJAVU_REGISTERED = False


def _try_register_cyrillic_font() -> None:
    """Регистрирует DejaVuSans (если есть в системе), чтобы кириллица не
    превращалась в чёрные квадраты. Идемпотентно."""
    global _FONT_NORMAL, _FONT_BOLD, _DEJAVU_REGISTERED
    if _DEJAVU_REGISTERED:
        return
    # Известные пути на разных системах.
    candidates_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    reg = next((p for p in candidates_regular if os.path.exists(p)), None)
    bold = next((p for p in candidates_bold if os.path.exists(p)), None)
    if reg is None:
        logger.warning(
            "DejaVuSans/Arial не найдены — PDF будет в Helvetica (без кириллицы)"
        )
        _DEJAVU_REGISTERED = True
        return
    try:
        pdfmetrics.registerFont(TTFont("ReportFont", reg))
        _FONT_NORMAL = "ReportFont"
        if bold is not None:
            pdfmetrics.registerFont(TTFont("ReportFontBold", bold))
            _FONT_BOLD = "ReportFontBold"
        else:
            _FONT_BOLD = "ReportFont"
    except Exception:
        logger.exception("Не удалось зарегистрировать шрифт для PDF")
    _DEJAVU_REGISTERED = True


# ---------- helpers ----------

def _fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _fmt_num(value: float | None, ndigits: int = 1) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.{ndigits}f}"


def _styles() -> dict[str, ParagraphStyle]:
    _try_register_cyrillic_font()
    base = getSampleStyleSheet()["BodyText"]
    return {
        "h1": ParagraphStyle(
            "h1", parent=base, fontName=_FONT_BOLD, fontSize=20,
            leading=24, spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base, fontName=_FONT_BOLD, fontSize=14,
            leading=18, spaceBefore=10, spaceAfter=6,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base, fontName=_FONT_BOLD, fontSize=11,
            leading=14, spaceBefore=8, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body", parent=base, fontName=_FONT_NORMAL, fontSize=10,
            leading=14,
        ),
        "muted": ParagraphStyle(
            "muted", parent=base, fontName=_FONT_NORMAL, fontSize=9,
            leading=12, textColor=colors.grey,
        ),
        "caption": ParagraphStyle(
            "caption", parent=base, fontName=_FONT_NORMAL, fontSize=8,
            leading=10, textColor=colors.grey, alignment=1,  # center
        ),
    }


# ---------- builder ----------

def build_pdf_report(
    report_data: ReportData,
    output_dir: str,
    period_code: str,
    filename: str | None = None,
) -> tuple[str, list[str]]:
    """Собирает PDF. Возвращает (pdf_path, chart_paths). Вызывающий должен
    удалить chart_paths (через cleanup_charts) и pdf_path после отправки.
    """
    _try_register_cyrillic_font()
    styles = _styles()

    if filename is None:
        filename = (
            f"report_{report_data.date_from.isoformat()}"
            f"_{report_data.date_to.isoformat()}.pdf"
        )
    pdf_path = os.path.join(output_dir, filename)

    started = _time.monotonic()
    story = []
    chart_paths: list[str] = []

    # ---------- 1. Обложка ----------
    story.append(Paragraph("Отчёт по состоянию", styles["h1"]))
    cover_lines = [
        f"Период: {_fmt_date(report_data.date_from)} — "
        f"{_fmt_date(report_data.date_to)} "
        f"({PERIOD_LABELS.get(period_code, period_code)})",
        f"Дата формирования: "
        f"{report_data.generated_at_local.strftime('%d.%m.%Y %H:%M')}",
        f"Часовой пояс: {report_data.timezone}",
    ]
    for line in cover_lines:
        story.append(Paragraph(line, styles["body"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        "Отчёт описывает наблюдаемую динамику и не заменяет медицинскую "
        "консультацию. Бот не ставит диагнозы.",
        styles["muted"],
    ))

    # ---------- 2. Саммари ----------
    story.append(Paragraph("Краткое саммари", styles["h2"]))
    summary_rows = [
        ("Дней с данными", str(report_data.days_with_data)),
        ("Всего опросов", str(report_data.total_surveys)),
        (
            "В среднем опросов в день",
            _fmt_num(report_data.surveys_per_day, 2) if report_data.days_with_data else "—",
        ),
        ("Медиана настроения", _scale_str(report_data.mood.median_value, 10)),
        ("Медиана тревоги", _scale_str(report_data.anxiety.median_value, 5)),
        ("Медиана энергии", _scale_str(report_data.energy.median_value, 5)),
        (
            "Медиана сна (часов)",
            _fmt_num(report_data.sleep.median_hours, 1),
        ),
    ]
    story.append(_kv_table(summary_rows))
    story.append(Paragraph(
        "Одна точка на дневных графиках = медиана ответов за день.",
        styles["caption"],
    ))

    # ---------- 3. Базовые графики ----------
    story.append(PageBreak())
    story.append(Paragraph("Базовые шкалы", styles["h2"]))
    _add_scale_block(
        story, styles, chart_paths,
        title="Настроение",
        daily=report_data.mood,
        max_value=10,
        output_dir=output_dir,
        filename="mood.png",
    )
    _add_scale_block(
        story, styles, chart_paths,
        title="Тревога",
        daily=report_data.anxiety,
        max_value=5,
        output_dir=output_dir,
        filename="anxiety.png",
    )
    _add_scale_block(
        story, styles, chart_paths,
        title="Энергия",
        daily=report_data.energy,
        max_value=5,
        output_dir=output_dir,
        filename="energy.png",
    )

    # ---------- 4. Сон ----------
    sleep = report_data.sleep
    story.append(PageBreak())
    story.append(Paragraph("Сон", styles["h2"]))
    sleep_path = report_charts.render_sleep_chart(
        sleep.by_date_hours, output_dir
    )
    if sleep_path:
        chart_paths.append(sleep_path)
        story.append(_image(sleep_path))
    sleep_rows = [
        ("Дней с заполненным сном", str(sleep.days_filled)),
        ("Медиана сна (часов)", _fmt_num(sleep.median_hours, 1)),
        ("Мин. сон (часов)", _fmt_num(sleep.min_hours, 1)),
        ("Макс. сон (часов)", _fmt_num(sleep.max_hours, 1)),
        ("Дополнительные сны (записей)", str(sleep.additional_sleeps)),
    ]
    story.append(_kv_table(sleep_rows))

    # ---------- 5. Лекарства ----------
    med = report_data.medication
    if med.days_filled:
        story.append(Paragraph("Лекарства", styles["h2"]))
        med_path = report_charts.render_medication_chart(
            med.by_value_count, output_dir
        )
        if med_path:
            chart_paths.append(med_path)
            story.append(_image(med_path))
        med_rows = [
            ("Дней с заполненной графой", str(med.days_filled)),
            ("Дней с приёмом (yes/partial)", str(med.days_with_intake)),
            (
                "Процент дней с приёмом",
                f"{med.percent_taken:.1f}%" if med.percent_taken is not None else "—",
            ),
        ]
        story.append(_kv_table(med_rows))
        story.append(Paragraph(
            "Цифры описывают только сам факт приёма, без оценки эффективности.",
            styles["muted"],
        ))

    # ---------- 6. Дополнительные системные вопросы ----------
    if report_data.optionals:
        story.append(PageBreak())
        story.append(Paragraph("Дополнительные вопросы", styles["h2"]))
        for opt in report_data.optionals:
            _add_optional_block(story, styles, chart_paths, opt, output_dir)

    # ---------- 7. Пользовательские вопросы ----------
    if report_data.customs:
        story.append(PageBreak())
        story.append(Paragraph("Свои вопросы", styles["h2"]))
        for c in report_data.customs:
            _add_custom_block(story, styles, chart_paths, c, output_dir)

    # ---------- 8. Менструальный цикл ----------
    if report_data.cycle_summary:
        story.append(PageBreak())
        story.append(Paragraph("Менструальный цикл", styles["h2"]))
        _add_cycle_block(story, styles, report_data.cycle_summary)

    # ---------- 9. Комментарии ----------
    if report_data.comments:
        story.append(PageBreak())
        story.append(Paragraph("Комментарии", styles["h2"]))
        for c in report_data.comments:
            line = f"<b>{_fmt_date(c.log_date)}</b> — {_escape_html(c.text)}"
            story.append(Paragraph(line, styles["body"]))
            story.append(Spacer(1, 0.1 * cm))

    # ---------- 10. Дневная таблица ----------
    if report_data.daily_table:
        story.append(PageBreak())
        story.append(Paragraph("Сводная таблица по дням", styles["h2"]))
        story.append(_daily_table(report_data))

    # ---------- собираем PDF ----------
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.6 * cm, bottomMargin=1.6 * cm,
        title="State report",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    duration_ms = int((_time.monotonic() - started) * 1000)
    logger.info(
        "pdf_report_build_finished tg=%s duration_ms=%s charts=%s size=%s",
        report_data.telegram_user_id, duration_ms,
        len(chart_paths), os.path.getsize(pdf_path),
    )
    return pdf_path, chart_paths


# ---------- блоки ----------

def _add_scale_block(
    story,
    styles,
    chart_paths: list[str],
    *,
    title: str,
    daily,
    max_value: float,
    output_dir: str,
    filename: str,
) -> None:
    story.append(Paragraph(title, styles["h3"]))
    if not daily.by_date:
        story.append(Paragraph("За период данных нет.", styles["muted"]))
        return
    path = report_charts.render_line_chart(
        daily.by_date,
        title=title,
        output_dir=output_dir,
        filename=filename,
        y_min=0,
        y_max=max_value,
        y_label=f"0–{int(max_value)}",
    )
    if path:
        chart_paths.append(path)
        story.append(_image(path))
    summary = (
        f"Медиана: {_scale_str(daily.median_value, max_value)}, "
        f"мин: {_scale_str(daily.min_value, max_value)}, "
        f"макс: {_scale_str(daily.max_value, max_value)}, "
        f"дней с данными: {daily.sample_days}"
    )
    story.append(Paragraph(summary, styles["body"]))


def _add_optional_block(
    story,
    styles,
    chart_paths: list[str],
    opt: OptionalStats,
    output_dir: str,
) -> None:
    title = opt.title or opt.code
    story.append(Paragraph(title, styles["h3"]))
    rendered_any = False

    # 1. Шкала: дневная медиана.
    if opt.by_date_median:
        # Грубо: длина опций в QUESTION_DEFINITIONS - 1 = верхняя граница.
        max_value = _scale_max_for(opt.code)
        path = report_charts.render_line_chart(
            opt.by_date_median,
            title=title,
            output_dir=output_dir,
            filename=f"opt_{opt.code}.png",
            y_min=0,
            y_max=max_value,
        )
        if path:
            chart_paths.append(path)
            story.append(_image(path))
            rendered_any = True
        summary = (
            f"Медиана: {_fmt_num(opt.median_value, 1)}, "
            f"мин: {_fmt_num(opt.min_value, 1)}, "
            f"макс: {_fmt_num(opt.max_value, 1)}, "
            f"дней: {len(opt.by_date_median)}"
        )
        story.append(Paragraph(summary, styles["body"]))

    # 2. Распределение вариантов (choice).
    if opt.choice_counter:
        # Сохраним порядок из QUESTION_DEFINITIONS, чтобы график читался
        # одинаково с UI настроек.
        order = QUESTION_DEFINITIONS.get(opt.code, {}).get("options")
        path = report_charts.render_bar_distribution(
            opt.choice_counter,
            title=f"{title} — распределение",
            output_dir=output_dir,
            filename=f"opt_{opt.code}_dist.png",
            order=order,
        )
        if path:
            chart_paths.append(path)
            story.append(_image(path))
            rendered_any = True

    if not rendered_any:
        story.append(Paragraph("За период данных нет.", styles["muted"]))


def _scale_max_for(code: str) -> float:
    """Возвращает верхнюю границу шкалы для кода вопроса. Используем кол-во
    опций в QUESTION_DEFINITIONS - 1; если не задано — 5."""
    opts = QUESTION_DEFINITIONS.get(code, {}).get("options")
    if not opts:
        return 5
    return max(len(opts) - 1, 1)


def _add_custom_block(
    story,
    styles,
    chart_paths: list[str],
    c: CustomStats,
    output_dir: str,
) -> None:
    suffix = " (архив)" if c.is_archived else ""
    story.append(Paragraph(f"{c.title}{suffix}", styles["h3"]))
    if c.answer_type == "scale_0_5" and c.by_date_median:
        path = report_charts.render_line_chart(
            c.by_date_median,
            title=c.title,
            output_dir=output_dir,
            filename=f"custom_{c.custom_question_id}.png",
            y_min=0, y_max=5,
            y_label="0–5",
        )
        if path:
            chart_paths.append(path)
            story.append(_image(path))
        story.append(Paragraph(
            f"Медиана: {_fmt_num(c.median_value, 1)}, "
            f"дней: {len(c.by_date_median)}",
            styles["body"],
        ))
    elif c.answer_type == "boolean":
        path = report_charts.render_boolean_frequency(
            c.bool_yes_days, c.bool_days,
            title=c.title,
            output_dir=output_dir,
            filename=f"custom_{c.custom_question_id}_bool.png",
        )
        if path:
            chart_paths.append(path)
            story.append(_image(path))
        if c.bool_days:
            pct = 100.0 * c.bool_yes_days / c.bool_days
            story.append(Paragraph(
                f"«Да» в {c.bool_yes_days} из {c.bool_days} ответов "
                f"({pct:.0f}%).",
                styles["body"],
            ))
    elif c.answer_type == "text":
        if not c.text_answers:
            story.append(Paragraph("За период ответов нет.", styles["muted"]))
        else:
            for d, t in c.text_answers:
                story.append(Paragraph(
                    f"<b>{_fmt_date(d)}</b> — {_escape_html(t)}",
                    styles["body"],
                ))
    else:
        story.append(Paragraph("За период данных нет.", styles["muted"]))


def _add_cycle_block(story, styles, cycle: dict) -> None:
    rows = []
    if cycle.get("cycle_day") is not None:
        rows.append(("Текущий день цикла", str(cycle["cycle_day"])))
    if cycle.get("latest_period_start"):
        rows.append(("Последнее начало", _fmt_date(cycle["latest_period_start"])))
    if cycle.get("latest_period_end"):
        rows.append(("Последнее окончание", _fmt_date(cycle["latest_period_end"])))
    if cycle.get("median_cycle_length"):
        rows.append((
            "Медианная длина цикла",
            f"{cycle['median_cycle_length']} дн.",
        ))
    if cycle.get("median_period_length"):
        rows.append((
            "Медианная длительность месячных",
            f"{cycle['median_period_length']} дн.",
        ))
    if cycle.get("predicted_next_start"):
        rows.append((
            "Примерное следующее начало",
            _fmt_date(cycle["predicted_next_start"]),
        ))
    if rows:
        story.append(_kv_table(rows))
    if cycle.get("low_confidence"):
        story.append(Paragraph(
            "Пока мало данных для надёжного прогноза. Используется "
            "стандартное значение 28 дней.",
            styles["muted"],
        ))


# ---------- мелкие компоненты ----------

def _kv_table(rows: list[tuple[str, str]]) -> Table:
    t = Table(rows, hAlign="LEFT", colWidths=[7 * cm, 8 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NORMAL),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
    ]))
    return t


def _image(path: str) -> Image:
    # Изображение во всю ширину контента (около 17 см на A4 с нашими полями).
    # _FIGSIZE = (7.0, 3.0) — соотношение ~2.33:1; берём 17×7.3 cm,
    # что близко по пропорциям, и matplotlib-чарты не растягиваются.
    return Image(path, width=17 * cm, height=7.3 * cm)


def _daily_table(report_data: ReportData) -> Table:
    header = ["Дата", "Настр.", "Трев.", "Эн.", "Сон, ч", "Коммент."]
    rows = [header]
    for r in report_data.daily_table:
        rows.append([
            _fmt_date(r.log_date),
            _fmt_num(r.mood, 1),
            _fmt_num(r.anxiety, 1),
            _fmt_num(r.energy, 1),
            _fmt_num(r.sleep_hours, 1),
            _escape_short(r.comment_excerpt or "", 28),
        ])
    t = Table(
        rows, hAlign="LEFT",
        colWidths=[2.5 * cm, 2 * cm, 2 * cm, 1.5 * cm, 1.8 * cm, 7 * cm],
        repeatRows=1,
    )
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), _FONT_NORMAL),
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 1), (-2, -1), "RIGHT"),
    ]))
    return t


def _scale_str(value: float | None, scale_max: float) -> str:
    if value is None:
        return "—"
    return f"{_fmt_num(value, 1)}/{int(scale_max)}"


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_short(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return _escape_html(text)


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont(_FONT_NORMAL, 8)
    canvas.setFillColor(colors.grey)
    page_text = f"Страница {doc.page}"
    canvas.drawRightString(A4[0] - 1.6 * cm, 1 * cm, page_text)
    canvas.drawString(1.6 * cm, 1 * cm, "Описательный отчёт. Не медицинский документ.")
    canvas.restoreState()


def cleanup_charts(paths: Iterable[str | None]) -> None:
    report_charts.cleanup_paths(paths)
