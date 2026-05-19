"""Generador de PDF de presupuesto con reportlab."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from . import config


@dataclass
class Item:
    descripcion: str
    cantidad: float
    precio_unitario: float

    @property
    def subtotal(self) -> float:
        return self.cantidad * self.precio_unitario


def _fmt_ars(monto: float) -> str:
    s = f"{monto:,.2f}"
    return "$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def generar_presupuesto(
    *,
    archivo: Path,
    numero: str,
    cliente_empresa: str,
    cliente_cuit: str,
    cliente_contacto: str | None,
    producto_nombre: str,
    items: list[Item],
    notas: str | None = None,
    validez_dias: int | None = None,
) -> Path:
    """Genera el PDF y devuelve la ruta. Sobrescribe si existe."""
    archivo.parent.mkdir(parents=True, exist_ok=True)
    validez_dias = validez_dias or config.PRESUPUESTO_VALIDEZ_DIAS

    doc = SimpleDocTemplate(
        str(archivo),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Presupuesto {numero}",
        author=config.EMPRESA_NOMBRE,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=9, leading=11)
    right = ParagraphStyle("right", parent=small, alignment=TA_RIGHT)
    bold = ParagraphStyle(
        "bold", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=10
    )
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14)
    foot = ParagraphStyle(
        "foot", parent=small, alignment=TA_CENTER, textColor=colors.grey
    )

    story: list = []

    encabezado = [
        [
            Paragraph(f"<b>{config.EMPRESA_NOMBRE}</b>", h1),
            Paragraph(
                f"Presupuesto N° <b>{numero}</b><br/>"
                f"Fecha: {datetime.now().strftime('%d/%m/%Y')}<br/>"
                f"Validez: {validez_dias} días",
                right,
            ),
        ]
    ]
    t = Table(encabezado, colWidths=[110 * mm, 64 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)

    empresa_info = " · ".join(
        x for x in (config.EMPRESA_WEB, config.EMPRESA_EMAIL, config.EMPRESA_TELEFONO) if x
    )
    if config.EMPRESA_CUIT:
        empresa_info = f"CUIT {config.EMPRESA_CUIT} · " + empresa_info
    if empresa_info:
        story.append(Paragraph(empresa_info, small))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("Cliente", bold))
    cliente_html = f"<b>{cliente_empresa}</b><br/>CUIT: {cliente_cuit}"
    if cliente_contacto:
        cliente_html += f"<br/>Contacto: {cliente_contacto}"
    story.append(Paragraph(cliente_html, body))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(f"Producto: <b>{producto_nombre}</b>", body))
    story.append(Spacer(1, 4 * mm))

    data = [["Descripción", "Cant.", "Precio unit.", "Subtotal"]]
    total = 0.0
    for it in items:
        data.append(
            [
                Paragraph(it.descripcion, body),
                f"{it.cantidad:g}",
                _fmt_ars(it.precio_unitario),
                _fmt_ars(it.subtotal),
            ]
        )
        total += it.subtotal
    data.append(["", "", "Total", _fmt_ars(total)])

    tabla = Table(data, colWidths=[95 * mm, 18 * mm, 30 * mm, 31 * mm])
    tabla.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -2), 0.25, colors.grey),
                ("BACKGROUND", (-2, -1), (-1, -1), colors.HexColor("#f3f4f6")),
                ("FONTNAME", (-2, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
            ]
        )
    )
    story.append(tabla)
    story.append(Spacer(1, 6 * mm))

    if notas:
        story.append(Paragraph("<b>Notas</b>", bold))
        story.append(Paragraph(notas.replace("\n", "<br/>"), body))
        story.append(Spacer(1, 4 * mm))

    vencimiento = (datetime.now() + timedelta(days=validez_dias)).strftime("%d/%m/%Y")
    story.append(
        Paragraph(
            f"Este presupuesto tiene validez hasta el {vencimiento}.", small
        )
    )
    story.append(Spacer(1, 8 * mm))
    story.append(
        Paragraph(
            "Forma de pago: transferencia bancaria. Emitimos Factura A.",
            small,
        )
    )

    story.append(Spacer(1, 16 * mm))
    story.append(Paragraph("Gracias por confiar en nosotros.", foot))

    doc.build(story)
    return archivo
