#!/usr/bin/env python3
"""Envía alertas de inventario y reportes semanales desde SQL Server."""

import argparse
import os
import smtplib
import ssl
import sys
from contextlib import closing
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pyodbc
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Falta configurar la variable de entorno {name}.")
    return value


def recipients_from_env(name: str) -> list[str]:
    recipients = [value.strip() for value in required_env(name).split(",") if value.strip()]
    if not recipients:
        raise ValueError(f"La variable {name} debe incluir al menos un correo.")
    return recipients


def open_database():
    return closing(
        pyodbc.connect(required_env("SQLSERVER_CONNECTION_STRING"), timeout=30)
    )


def send_email(message: EmailMessage, recipients: list[str]) -> None:
    host = required_env("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    sender = required_env("EMAIL_FROM")
    username = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise ValueError("Configure SMTP_USER y SMTP_PASSWORD juntos, o deje ambos vacíos.")

    message["From"] = sender
    message["To"] = ", ".join(recipients)
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        server.starttls(context=ssl.create_default_context())
        server.ehlo()
        if username:
            server.login(username, password)
        refused = server.send_message(message, from_addr=sender, to_addrs=recipients)
    if refused:
        raise RuntimeError(f"El servidor rechazó destinatarios: {', '.join(refused)}")


def rows_as_dicts(cursor) -> list[dict[str, Any]]:
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def check_stock_alerts() -> int:
    sent_count = 0
    with open_database() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT a.AlertaInventarioID, a.EquipoID, e.Nombre AS Equipo,
                   e.Categoria, a.StockAlGenerar, e.StockMinimo,
                   a.FechaGeneracion
            FROM dbo.AlertaInventarioOutbox AS a
            INNER JOIN dbo.DimEquipo AS e ON e.EquipoID = a.EquipoID
            WHERE a.CorreoEnviadoEn IS NULL
            ORDER BY a.AlertaInventarioID
            """
        )
        alerts = rows_as_dicts(cursor)
        recipients = recipients_from_env("EMAIL_TO_LOGISTICA") if alerts else []

        for alert in alerts:
            message = EmailMessage()
            message["Subject"] = f"Alerta de inventario: quiebre de stock - {alert['Equipo']}"
            message.set_content(
                "Se detectó un quiebre de stock en un equipo crítico.\n\n"
                f"Equipo: {alert['Equipo']} ({alert['EquipoID']})\n"
                f"Categoría: {alert['Categoria']}\n"
                f"Stock registrado: {alert['StockAlGenerar']}\n"
                f"Stock mínimo: {alert['StockMinimo']}\n"
                f"Fecha de detección: {alert['FechaGeneracion']}\n\n"
                "Revise el inventario y gestione la reposición."
            )
            try:
                send_email(message, recipients)
            except (OSError, RuntimeError, smtplib.SMTPException) as error:
                cursor.execute(
                    """
                    UPDATE dbo.AlertaInventarioOutbox
                    SET UltimoError = ?
                    WHERE AlertaInventarioID = ? AND CorreoEnviadoEn IS NULL
                    """,
                    str(error)[:1000],
                    alert["AlertaInventarioID"],
                )
                connection.commit()
                print(
                    f"No se pudo enviar la alerta {alert['AlertaInventarioID']}: {error}",
                    file=sys.stderr,
                )
                raise

            cursor.execute(
                """
                UPDATE dbo.AlertaInventarioOutbox
                SET CorreoEnviadoEn = SYSDATETIME(), UltimoError = NULL
                WHERE AlertaInventarioID = ? AND CorreoEnviadoEn IS NULL
                """,
                alert["AlertaInventarioID"],
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"No se pudo registrar el envío de la alerta "
                    f"{alert['AlertaInventarioID']}."
                )
            connection.commit()
            sent_count += 1

    print(f"Alertas de inventario enviadas: {sent_count}")
    return sent_count


def summarize_weekly_data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sla_values = [row["SLA_Cumplido"] for row in rows if row["SLA_Cumplido"] is not None]
    sla_met = sum(bool(value) for value in sla_values)
    return {
        "tickets_total": len(rows),
        "tickets_closed": sum(row["FechaCierre"] is not None for row in rows),
        "sla_evaluable": len(sla_values),
        "sla_met": sla_met,
        "sla_compliance_pct": (sla_met / len(sla_values) * 100) if sla_values else 0.0,
        "voltage_alerts": sum(row["AlertaTension"] == "ALERTA" for row in rows),
        "overdue_open": sum(
            row["FechaCierre"] is None
            and row["SLA_Cumplido"] is not None
            and not bool(row["SLA_Cumplido"])
            for row in rows
        ),
    }


def create_weekly_pdf(rows: list[dict[str, Any]], output_path: Path) -> dict[str, Any]:
    summary = summarize_weekly_data(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        alignment=TA_CENTER,
        textColor=colors.HexColor("#15324b"),
    )
    story = [
        Paragraph("Reporte operativo semanal", title_style),
        Paragraph(
            f"Generado: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
            styles["Normal"],
        ),
        Spacer(1, 14),
        Paragraph("Indicadores de atención", styles["Heading2"]),
    ]

    metrics = [
        ["Indicador", "Resultado"],
        ["Tickets recibidos", str(summary["tickets_total"])],
        ["Tickets cerrados", str(summary["tickets_closed"])],
        [
            "Cumplimiento SLA",
            f"{summary['sla_compliance_pct']:.1f}% "
            f"({summary['sla_met']}/{summary['sla_evaluable']} evaluables)",
        ],
        ["Tickets abiertos con SLA vencido", str(summary["overdue_open"])],
        ["Alertas de tensión", str(summary["voltage_alerts"])],
    ]
    story.append(Table(metrics, colWidths=(3.6 * inch, 3.5 * inch), hAlign="LEFT"))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Tickets con alerta de tensión", styles["Heading2"]))

    voltage_alert_rows = [row for row in rows if row["AlertaTension"] == "ALERTA"]
    if voltage_alert_rows:
        alert_table = [["Ticket", "Cliente", "Equipo", "Voltaje", "Rango permitido"]]
        for row in voltage_alert_rows[:25]:
            alert_table.append(
                [
                    str(row["TicketID"]),
                    Paragraph(escape(str(row["Cliente"])), styles["BodyText"]),
                    Paragraph(escape(str(row["Equipo"])), styles["BodyText"]),
                    str(row["VoltajeMedido"]),
                    f"{row['VoltajeMinimo']} - {row['VoltajeMaximo']} V",
                ]
            )
        table = Table(
            alert_table,
            colWidths=(0.8 * inch, 1.65 * inch, 1.7 * inch, 0.9 * inch, 1.55 * inch),
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15324b")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b8c5ce")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f8")]),
                ]
            )
        )
        story.append(table)
        if len(voltage_alert_rows) > 25:
            story.append(
                Paragraph(
                    f"Se muestran 25 de {len(voltage_alert_rows)} alertas. "
                    "Consulte la vista vw_AnaliticaOperativa para el detalle completo.",
                    styles["Italic"],
                )
            )
    else:
        story.append(Paragraph("No se registraron alertas de tensión esta semana.", styles["Normal"]))

    document.build(story)
    return summary


def send_weekly_report() -> Path:
    with open_database() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT TicketID, FechaApertura, FechaCierre, Cliente, Equipo,
                   VoltajeMedido, VoltajeMinimo, VoltajeMaximo,
                   SLA_Cumplido, AlertaTension
            FROM dbo.vw_AnaliticaOperativa
            WHERE FechaApertura >= DATEADD(DAY, -7, SYSDATETIME())
              AND FechaApertura < SYSDATETIME()
            ORDER BY FechaApertura DESC
            """
        )
        rows = rows_as_dicts(cursor)

    report_dir = Path(os.getenv("REPORT_OUTPUT_DIR", "reportes"))
    filename = f"reporte_operativo_semanal_{datetime.now():%Y-%m-%d}.pdf"
    output_path = report_dir / filename
    summary = create_weekly_pdf(rows, output_path)

    message = EmailMessage()
    message["Subject"] = (
        f"Reporte operativo semanal - cumplimiento SLA "
        f"{summary['sla_compliance_pct']:.1f}%"
    )
    message.set_content(
        "Adjunto se encuentra el reporte operativo de los últimos siete días.\n\n"
        f"Tickets: {summary['tickets_total']}\n"
        f"Cumplimiento SLA: {summary['sla_compliance_pct']:.1f}%\n"
        f"Alertas de tensión: {summary['voltage_alerts']}\n"
        f"Tickets abiertos con SLA vencido: {summary['overdue_open']}\n"
    )
    message.add_attachment(
        output_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=filename,
    )
    send_email(message, recipients_from_env("EMAIL_TO_GERENCIA"))
    print(f"Reporte enviado a gerencia: {output_path.resolve()}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check-stock", action="store_true", help="Procesa alertas de quiebre pendientes")
    actions.add_argument("--weekly-report", action="store_true", help="Genera y envía el PDF de los últimos 7 días")
    actions.add_argument("--run-all", action="store_true", help="Procesa alertas y envía el PDF")
    args = parser.parse_args()

    if args.check_stock or args.run_all:
        check_stock_alerts()
    if args.weekly_report or args.run_all:
        send_weekly_report()


if __name__ == "__main__":
    main()
