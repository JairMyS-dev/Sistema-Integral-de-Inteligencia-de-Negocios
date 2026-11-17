#!/usr/bin/env python3
"""Carga de forma idempotente los CSV/XLSX generados hacia SQL Server."""

import argparse
import csv
import os
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import openpyxl
import pyodbc


def read_csv(path: Path, required_columns: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        actual_columns = set(reader.fieldnames or ())
        missing = required_columns - actual_columns
        if missing:
            raise ValueError(f"{path}: faltan columnas requeridas: {', '.join(sorted(missing))}")
        return list(reader)


def read_inventory(path: Path) -> list[dict[str, object]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook["Inventario"]
        rows = sheet.iter_rows(values_only=True)
        headers = next(rows, None)
        if headers is None:
            raise ValueError(f"{path}: la hoja Inventario está vacía.")
        header_names = [str(value) if value is not None else "" for value in headers]
        required = {
            "EquipoID",
            "Nombre",
            "Categoria",
            "EsCritico",
            "StockActual",
            "StockMinimo",
            "CostoUnitario",
        }
        missing = required - set(header_names)
        if missing:
            raise ValueError(f"{path}: faltan columnas requeridas: {', '.join(sorted(missing))}")
        return [
            dict(zip(header_names, values))
            for values in rows
            if any(value is not None for value in values)
        ]
    finally:
        workbook.close()


def unique_by_id(rows: list[dict], key: str, source: str) -> list[dict]:
    found: set[str] = set()
    for row in rows:
        identifier = str(row[key]).strip()
        if not identifier:
            raise ValueError(f"{source}: {key} no puede estar vacío.")
        if identifier in found:
            raise ValueError(f"{source}: identificador duplicado {identifier} en {key}.")
        found.add(identifier)
    return rows


def upsert(
    cursor,
    table: str,
    key_column: str,
    update_sql: str,
    insert_sql: str,
    rows: list[dict],
    update_values,
    insert_values,
) -> None:
    if not rows:
        return
    existing = {
        row[0]
        for row in cursor.execute(f"SELECT {key_column} FROM {table}").fetchall()
    }
    updates = [update_values(row) for row in rows if row[key_column] in existing]
    inserts = [insert_values(row) for row in rows if row[key_column] not in existing]
    if updates:
        cursor.executemany(update_sql, updates)
    if inserts:
        cursor.executemany(insert_sql, inserts)


def load_data(data_dir: Path) -> dict[str, int]:
    sales = unique_by_id(
        read_csv(
            data_dir / "ventas_crm.csv",
            {
                "VentaID",
                "Fecha",
                "ClienteID",
                "ClienteNombre",
                "Sector",
                "Servicio",
                "PresupuestoEstimado",
                "Estado",
            },
        ),
        "VentaID",
        "ventas_crm.csv",
    )
    tickets = unique_by_id(
        read_csv(
            data_dir / "tickets_operativos.csv",
            {
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
            },
        ),
        "TicketID",
        "tickets_operativos.csv",
    )
    inventory = unique_by_id(
        read_inventory(data_dir / "inventario.xlsx"), "EquipoID", "inventario.xlsx"
    )

    clients_by_id: dict[str, dict[str, str]] = {}
    for sale in sales:
        client = {
            "ClienteID": sale["ClienteID"].strip(),
            "Nombre": sale["ClienteNombre"].strip(),
            "Sector": sale["Sector"].strip(),
        }
        previous = clients_by_id.get(client["ClienteID"])
        if previous is not None and previous != client:
            raise ValueError(f"ventas_crm.csv: datos contradictorios para {client['ClienteID']}.")
        clients_by_id[client["ClienteID"]] = client

    equipment_ids = {row["EquipoID"] for row in inventory}
    client_ids = set(clients_by_id)
    for ticket in tickets:
        if ticket["ClienteID"] not in client_ids:
            raise ValueError(
                f"Ticket {ticket['TicketID']}: ClienteID {ticket['ClienteID']} "
                "no aparece en ventas_crm.csv."
            )
        if ticket["EquipoID"] not in equipment_ids:
            raise ValueError(
                f"Ticket {ticket['TicketID']}: EquipoID {ticket['EquipoID']} "
                "no aparece en inventario.xlsx."
            )

    connection_string = os.getenv("SQLSERVER_CONNECTION_STRING", "").strip()
    if not connection_string:
        raise ValueError("Falta configurar la variable SQLSERVER_CONNECTION_STRING.")

    with closing(pyodbc.connect(connection_string, timeout=30)) as connection:
        with connection:
            cursor = connection.cursor()
            client_rows = list(clients_by_id.values())
            upsert(
                cursor,
                "dbo.DimCliente",
                "ClienteID",
                "UPDATE dbo.DimCliente SET Nombre = ?, Sector = ? WHERE ClienteID = ?",
                "INSERT INTO dbo.DimCliente (Nombre, Sector, ClienteID) VALUES (?, ?, ?)",
                client_rows,
                lambda row: (row["Nombre"], row["Sector"], row["ClienteID"]),
                lambda row: (row["Nombre"], row["Sector"], row["ClienteID"]),
            )
            upsert(
                cursor,
                "dbo.DimEquipo",
                "EquipoID",
                """
                UPDATE dbo.DimEquipo
                SET Nombre = ?, Categoria = ?, EsCritico = ?, StockActual = ?,
                    StockMinimo = ?, CostoUnitario = ?
                WHERE EquipoID = ?
                """,
                """
                INSERT INTO dbo.DimEquipo
                    (Nombre, Categoria, EsCritico, StockActual, StockMinimo, CostoUnitario, EquipoID)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                inventory,
                lambda row: (
                    row["Nombre"],
                    row["Categoria"],
                    int(row["EsCritico"]),
                    int(row["StockActual"]),
                    int(row["StockMinimo"]),
                    Decimal(str(row["CostoUnitario"])),
                    row["EquipoID"],
                ),
                lambda row: (
                    row["Nombre"],
                    row["Categoria"],
                    int(row["EsCritico"]),
                    int(row["StockActual"]),
                    int(row["StockMinimo"]),
                    Decimal(str(row["CostoUnitario"])),
                    row["EquipoID"],
                ),
            )
            upsert(
                cursor,
                "dbo.FactVenta",
                "VentaID",
                """
                UPDATE dbo.FactVenta
                SET Fecha = ?, ClienteID = ?, Servicio = ?, PresupuestoEstimado = ?, Estado = ?
                WHERE VentaID = ?
                """,
                """
                INSERT INTO dbo.FactVenta
                    (Fecha, ClienteID, Servicio, PresupuestoEstimado, Estado, VentaID)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                sales,
                lambda row: (
                    date.fromisoformat(row["Fecha"]),
                    row["ClienteID"],
                    row["Servicio"],
                    Decimal(row["PresupuestoEstimado"]),
                    row["Estado"],
                    row["VentaID"],
                ),
                lambda row: (
                    date.fromisoformat(row["Fecha"]),
                    row["ClienteID"],
                    row["Servicio"],
                    Decimal(row["PresupuestoEstimado"]),
                    row["Estado"],
                    row["VentaID"],
                ),
            )
            upsert(
                cursor,
                "dbo.FactTicket",
                "TicketID",
                """
                UPDATE dbo.FactTicket
                SET FechaApertura = ?, FechaCierre = ?, ClienteID = ?, EquipoID = ?,
                    TipoServicio = ?, Prioridad = ?, SLAObjetivoHoras = ?, VoltajeMedido = ?,
                    VoltajeMinimo = ?, VoltajeMaximo = ?, EstadoTicket = ?
                WHERE TicketID = ?
                """,
                """
                INSERT INTO dbo.FactTicket
                    (FechaApertura, FechaCierre, ClienteID, EquipoID, TipoServicio, Prioridad,
                     SLAObjetivoHoras, VoltajeMedido, VoltajeMinimo, VoltajeMaximo, EstadoTicket, TicketID)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tickets,
                lambda row: (
                    datetime.fromisoformat(row["FechaApertura"]),
                    datetime.fromisoformat(row["FechaCierre"]) if row["FechaCierre"] else None,
                    row["ClienteID"],
                    row["EquipoID"],
                    row["TipoServicio"],
                    row["Prioridad"],
                    int(row["SLAObjetivoHoras"]),
                    Decimal(row["VoltajeMedido"]),
                    Decimal(row["VoltajeMinimo"]),
                    Decimal(row["VoltajeMaximo"]),
                    row["EstadoTicket"],
                    row["TicketID"],
                ),
                lambda row: (
                    datetime.fromisoformat(row["FechaApertura"]),
                    datetime.fromisoformat(row["FechaCierre"]) if row["FechaCierre"] else None,
                    row["ClienteID"],
                    row["EquipoID"],
                    row["TipoServicio"],
                    row["Prioridad"],
                    int(row["SLAObjetivoHoras"]),
                    Decimal(row["VoltajeMedido"]),
                    Decimal(row["VoltajeMinimo"]),
                    Decimal(row["VoltajeMaximo"]),
                    row["EstadoTicket"],
                    row["TicketID"],
                ),
            )

    return {
        "clientes": len(clients_by_id),
        "equipos": len(inventory),
        "ventas": len(sales),
        "tickets": len(tickets),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("datos_generados"))
    args = parser.parse_args()
    counts = load_data(args.data_dir)
    print(
        "Carga completada: "
        + ", ".join(f"{count} {name}" for name, count in counts.items())
    )


if __name__ == "__main__":
    main()
