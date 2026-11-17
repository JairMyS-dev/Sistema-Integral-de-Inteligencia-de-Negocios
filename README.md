# Sistema Integral de Inteligencia de Negocios

Proyecto de portafolio que integra datos sintéticos de CRM, inventario y soporte técnico en SQL Server. Incluye carga reproducible, vistas analíticas y notificaciones automáticas por correo para quiebres de stock y resultados operativos semanales.

## Alcance implementado

- `Generador-de-Datos.py`: crea oportunidades CRM en CSV, inventario en Excel y tickets de soporte en CSV.
- `Modelado-Analiticas.sql`: define dimensiones, hechos, vistas de análisis, restricciones de integridad y una bandeja de salida transaccional para quiebres de stock.
- `cargar_datos.py`: valida relaciones y carga los tres archivos en SQL Server con inserción/actualización por clave, dentro de una transacción.
- `automatizacion_notificaciones.py`: envía alertas pendientes de inventario y genera/envía el PDF semanal de SLA y tensión eléctrica.
- Los datos generados y los PDF locales se excluyen del control de versiones.

La automatización se implementa en Python. No requiere AWS; puede conectarse a una instancia SQL Server local, en una máquina virtual o en Amazon RDS para SQL Server. El paquete SSIS y el dashboard Power BI no forman parte del flujo ejecutable de esta versión.

## Requisitos

- Python 3.10 o posterior.
- SQL Server y el controlador ODBC de SQL Server instalado en el equipo que ejecuta los scripts.
- Una cuenta SMTP con STARTTLS y direcciones de correo autorizadas.

Instale las dependencias:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

En Linux, `pyodbc` requiere además el controlador ODBC de Microsoft SQL Server disponible para el sistema operativo. Instale el controlador de acuerdo con la guía oficial de Microsoft antes de usar los scripts.

## Puesta en marcha

1. Cree una base de datos en SQL Server y ejecute [`Modelado-Analiticas.sql`](./Modelado-Analiticas.sql) en ella. El script crea el modelo y las vistas, pero no crea la base de datos ni configura usuarios, firewall o recursos de AWS.
2. Genere los archivos sintéticos:

   ```bash
   python Generador-de-Datos.py --output-dir datos_generados --ventas 1500 --tickets 4000
   ```

   El generador produce `ventas_crm.csv`, `inventario.xlsx` y `tickets_operativos.csv`. Puede cambiar la cantidad de registros y la semilla con `--ventas`, `--tickets` y `--seed`.
3. Configure `SQLSERVER_CONNECTION_STRING` en el entorno del sistema. Ejemplo de formato para ODBC Driver 18:

   ```text
   Driver={ODBC Driver 18 for SQL Server};Server=tcp:servidor,1433;Database=NegociosBI;UID=usuario;PWD=contraseña;Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;
   ```

   Use un gestor de secretos o el almacén seguro del programador de tareas para credenciales reales; no las guarde en el repositorio.
4. Cargue las dimensiones y los hechos:

   ```bash
   python cargar_datos.py --data-dir datos_generados
   ```

   La carga inserta o actualiza cada registro usando sus IDs de origen. Se ejecuta en una transacción y valida que cada ticket tenga cliente y equipo existentes. Al importar por primera vez un equipo crítico con stock cero, SQL Server registra automáticamente una alerta pendiente.
5. Configure las variables SMTP antes de ejecutar la automatización:

   ```text
   SMTP_HOST=smtp.ejemplo.com
   SMTP_PORT=587
   SMTP_USER=usuario-smtp
   SMTP_PASSWORD=secreto-smtp
   EMAIL_FROM=bi@ejemplo.com
   EMAIL_TO_LOGISTICA=jefatura-logistica@ejemplo.com
   EMAIL_TO_GERENCIA=gerencia@ejemplo.com
   REPORT_OUTPUT_DIR=reportes
   ```

   `SMTP_USER` y `SMTP_PASSWORD` se configuran juntos o se dejan ambos vacíos si el servidor permite relay autenticado por red. El script siempre usa STARTTLS. Defina las variables en el entorno del proceso; no se carga un archivo `.env`.

## Automatización

Ejecute la revisión de inventario con la frecuencia deseada:

```bash
python automatizacion_notificaciones.py --check-stock
```

Se recomienda programarla cada minuto con el Programador de tareas de Windows o `cron`. El trigger SQL registra el evento cuando un equipo crítico pasa a cero; la notificación usa esa bandeja persistente, por lo que reiniciar el proceso no descarta alertas pendientes.

Genere y envíe el informe semanal de los últimos siete días:

```bash
python automatizacion_notificaciones.py --weekly-report
```

Programe este comando una vez por semana (por ejemplo, cada lunes). El PDF se guarda localmente bajo `reportes/` y se adjunta al correo de gerencia. Incluye volumen de tickets, cumplimiento SLA entre los tickets evaluables, tickets abiertos con SLA vencido y el detalle de hasta 25 alertas de tensión; el resto se resume en el reporte y está disponible en la vista SQL.

Para ejecutar ambas acciones manualmente:

```bash
python automatizacion_notificaciones.py --run-all
```

Configure un único proceso de revisión simultáneo para evitar envíos duplicados. El envío SMTP y el registro en la base no pueden formar una transacción distribuida: si el servidor acepta un correo y la conexión a SQL Server falla antes de marcarlo como enviado, ese correo podría repetirse en el siguiente intento. Los fallos de envío se guardan en `dbo.AlertaInventarioOutbox.UltimoError` y la alerta queda pendiente para reintento.

## Vistas analíticas

- `dbo.vw_AnaliticaComercial`: oportunidades con cliente, sector, presupuesto y estado.
- `dbo.vw_AnaliticaOperativa`: tickets con dimensiones, costo unitario, evaluación de SLA y alerta de tensión.
- `dbo.vw_AlertasInventario`: estado actual (`QUIEBRE DE STOCK`, `BAJO MÍNIMO` o `NORMAL`).

La consulta semanal considera tickets abiertos en los siete días anteriores. Los tickets abiertos cuyo SLA todavía no vence no se incluyen en el denominador de cumplimiento.

## Validación local

```bash
python -m unittest discover -s tests
python -m py_compile Generador-de-Datos.py cargar_datos.py automatizacion_notificaciones.py
```

Los correos y la conexión SQL requieren credenciales e infraestructura propias; las pruebas locales no los ejecutan.
