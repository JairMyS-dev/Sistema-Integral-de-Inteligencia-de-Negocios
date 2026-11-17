#!/usr/bin/env python3
"""Genera archivos sintéticos compatibles con Modelado-Analiticas.sql."""

import argparse
import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook


CLIENTES = [
    ("CLI-001", "Andes Salud", "Salud"),
    ("CLI-002", "Norte Logística", "Logística"),
    ("CLI-003", "Grupo Horizonte", "Comercio"),
    ("CLI-004", "Clínica del Valle", "Salud"),
    ("CLI-005", "Industrias del Pacífico", "Manufactura"),
    ("CLI-006", "Colegio Nuevo Mundo", "Educación"),
    ("CLI-007", "Financiera Central", "Finanzas"),
    ("CLI-008", "Hoteles Mirador", "Turismo"),
    ("CLI-009", "Distribuidora Sol", "Comercio"),
    ("CLI-010", "Municipalidad del Este", "Gobierno"),
    ("CLI-011", "Laboratorios Vida", "Salud"),
    ("CLI-012", "Transportes Ruta 5", "Logística"),
    ("CLI-013", "Universidad Metropolitana", "Educación"),
    ("CLI-014", "Alimentos Cumbre", "Manufactura"),
    ("CLI-015", "Cooperativa Unión", "Finanzas"),
    ("CLI-016", "Centro Empresarial Sur", "Servicios"),
    ("CLI-017", "Agroexportadora Campo", "Agricultura"),
    ("CLI-018", "Residencial Los Robles", "Inmobiliario"),
    ("CLI-019", "Clínica San Gabriel", "Salud"),
    ("CLI-020", "Bodegas del Puerto", "Logística"),
]

EQUIPOS = [
    ("EQ-001", "UPS 10 kVA", "Respaldo eléctrico", 1, 0, 3, 2450.00),
    ("EQ-002", "UPS 3 kVA", "Respaldo eléctrico", 1, 8, 4, 840.00),
    ("EQ-003", "Cable UTP Cat 6 (caja)", "Cableado estructurado", 1, 2, 5, 125.00),
    ("EQ-004", "Bobina de fibra óptica", "Cableado estructurado", 1, 6, 3, 410.00),
    ("EQ-005", "Transformador 220/110 V", "Respaldo eléctrico", 1, 4, 2, 690.00),
    ("EQ-006", "Cerradura inteligente", "Domótica", 0, 12, 4, 180.00),
    ("EQ-007", "Cámara IP 4K", "Videovigilancia", 1, 14, 5, 235.00),
    ("EQ-008", "Switch PoE 24 puertos", "Redes", 1, 0, 3, 520.00),
    ("EQ-009", "Sensor de voltaje", "Telemetría", 0, 18, 5, 95.00),
    ("EQ-010", "Router de borde", "Redes", 1, 7, 3, 375.00),
]

SERVICIOS = (
    "Domótica",
    "Videovigilancia",
    "Circuito dedicado",
    "Cableado estructurado",
    "Soporte eléctrico",
    "Telemetría",
)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generar_datos(output_dir: Path, ventas_count: int, tickets_count: int, seed: int) -> None:
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now().replace(microsecond=0)
    hoy = ahora.date()

    ventas = []
    for index in range(1, ventas_count + 1):
        cliente_id, cliente_nombre, sector = rng.choice(CLIENTES)
        ventas.append(
            {
                "VentaID": f"VEN-{index:06d}",
                "Fecha": (hoy - timedelta(days=rng.randint(0, 364))).isoformat(),
                "ClienteID": cliente_id,
                "ClienteNombre": cliente_nombre,
                "Sector": sector,
                "Servicio": rng.choice(SERVICIOS),
                "PresupuestoEstimado": f"{rng.uniform(500, 30000):.2f}",
                "Estado": rng.choices(
                    ("Ganado", "Perdido", "En negociación"), weights=(45, 30, 25)
                )[0],
            }
        )
    write_csv(
        output_dir / "ventas_crm.csv",
        (
            "VentaID",
            "Fecha",
            "ClienteID",
            "ClienteNombre",
            "Sector",
            "Servicio",
            "PresupuestoEstimado",
            "Estado",
        ),
        ventas,
    )

    inventory_book = Workbook()
    inventory_sheet = inventory_book.active
    inventory_sheet.title = "Inventario"
    inventory_sheet.append(
        ("EquipoID", "Nombre", "Categoria", "EsCritico", "StockActual", "StockMinimo", "CostoUnitario")
    )
    for equipment in EQUIPOS:
        inventory_sheet.append(equipment)
    inventory_book.save(output_dir / "inventario.xlsx")

    tickets = []
    for index in range(1, tickets_count + 1):
        opened = ahora - timedelta(days=rng.randint(0, 364), minutes=rng.randint(0, 1439))
        target_hours = rng.choice((4, 8, 12, 24))
        closed = (
            opened + timedelta(minutes=rng.randint(30, 36 * 60))
            if rng.random() < 0.9
            else None
        )
        low_voltage, high_voltage = 110.0, 127.0
        voltage = (
            rng.choice((rng.uniform(104, 109.9), rng.uniform(127.1, 133)))
            if rng.random() < 0.06
            else rng.uniform(115, 124)
        )
        tickets.append(
            {
                "TicketID": f"TIC-{index:06d}",
                "FechaApertura": opened.isoformat(timespec="seconds"),
                "FechaCierre": closed.isoformat(timespec="seconds") if closed else "",
                "ClienteID": rng.choice(CLIENTES)[0],
                "EquipoID": rng.choice(EQUIPOS)[0],
                "TipoServicio": rng.choice(SERVICIOS),
                "Prioridad": rng.choice(("Baja", "Media", "Alta", "Crítica")),
                "SLAObjetivoHoras": target_hours,
                "VoltajeMedido": f"{voltage:.2f}",
                "VoltajeMinimo": f"{low_voltage:.2f}",
                "VoltajeMaximo": f"{high_voltage:.2f}",
                "EstadoTicket": "Cerrado" if closed else "Abierto",
            }
        )
    write_csv(
        output_dir / "tickets_operativos.csv",
        (
            "TicketID",
            "FechaApertura",
            "FechaCierre",
            "ClienteID",
            "EquipoID",
            "TipoServicio",
            "Prioridad",
            "SLAObjetivoHoras",
            "VoltajeMedido",
            "VoltajeMinimo",
            "VoltajeMaximo",
            "EstadoTicket",
        ),
        tickets,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("datos_generados"))
    parser.add_argument("--ventas", type=int, default=1500, help="Cantidad de oportunidades CRM")
    parser.add_argument("--tickets", type=int, default=4000, help="Cantidad de tickets")
    parser.add_argument("--seed", type=int, default=42, help="Semilla para reproducir los datos")
    args = parser.parse_args()
    if args.ventas < 0 or args.tickets < 0:
        parser.error("--ventas y --tickets deben ser mayores o iguales a cero")

    generar_datos(args.output_dir, args.ventas, args.tickets, args.seed)
    print(f"Archivos sintéticos generados en: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
