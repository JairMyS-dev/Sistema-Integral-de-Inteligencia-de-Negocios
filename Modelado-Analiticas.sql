/*
  Modelo dimensional para SQL Server.
  Ejecute este script en la base de datos de destino antes de cargar los CSV/XLSX.
  Cargue primero DimCliente y DimEquipo; después FactVenta y FactTicket.
*/

IF OBJECT_ID('dbo.DimCliente', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.DimCliente
    (
        ClienteID       VARCHAR(20)    NOT NULL PRIMARY KEY,
        Nombre          NVARCHAR(150)  NOT NULL,
        Sector          NVARCHAR(80)   NOT NULL
    );
END;
GO

IF OBJECT_ID('dbo.DimEquipo', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.DimEquipo
    (
        EquipoID        VARCHAR(20)    NOT NULL PRIMARY KEY,
        Nombre          NVARCHAR(150)  NOT NULL,
        Categoria       NVARCHAR(80)   NOT NULL,
        EsCritico       BIT            NOT NULL,
        StockActual     INT            NOT NULL,
        StockMinimo     INT            NOT NULL,
        CostoUnitario   DECIMAL(12, 2) NOT NULL,
        CONSTRAINT CK_DimEquipo_Stock CHECK (StockActual >= 0 AND StockMinimo >= 0),
        CONSTRAINT CK_DimEquipo_Costo CHECK (CostoUnitario >= 0)
    );
END;
GO

IF OBJECT_ID('dbo.FactVenta', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FactVenta
    (
        VentaID             VARCHAR(24)    NOT NULL PRIMARY KEY,
        Fecha               DATE           NOT NULL,
        ClienteID           VARCHAR(20)    NOT NULL,
        Servicio            NVARCHAR(100)  NOT NULL,
        PresupuestoEstimado DECIMAL(14, 2) NOT NULL,
        Estado              VARCHAR(30)    NOT NULL,
        CONSTRAINT FK_FactVenta_Cliente FOREIGN KEY (ClienteID)
            REFERENCES dbo.DimCliente (ClienteID),
        CONSTRAINT CK_FactVenta_Presupuesto CHECK (PresupuestoEstimado >= 0),
        CONSTRAINT CK_FactVenta_Estado CHECK (Estado IN ('Ganado', 'Perdido', 'En negociación'))
    );
END;
GO

IF OBJECT_ID('dbo.FactTicket', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.FactTicket
    (
        TicketID          VARCHAR(24)    NOT NULL PRIMARY KEY,
        FechaApertura     DATETIME2(0)   NOT NULL,
        FechaCierre       DATETIME2(0)   NULL,
        ClienteID         VARCHAR(20)    NOT NULL,
        EquipoID          VARCHAR(20)    NOT NULL,
        TipoServicio      NVARCHAR(100)  NOT NULL,
        Prioridad         NVARCHAR(20)   NOT NULL,
        SLAObjetivoHoras  SMALLINT       NOT NULL,
        VoltajeMedido     DECIMAL(7, 2)  NOT NULL,
        VoltajeMinimo     DECIMAL(7, 2)  NOT NULL,
        VoltajeMaximo     DECIMAL(7, 2)  NOT NULL,
        EstadoTicket      VARCHAR(20)    NOT NULL,
        CONSTRAINT FK_FactTicket_Cliente FOREIGN KEY (ClienteID)
            REFERENCES dbo.DimCliente (ClienteID),
        CONSTRAINT FK_FactTicket_Equipo FOREIGN KEY (EquipoID)
            REFERENCES dbo.DimEquipo (EquipoID),
        CONSTRAINT CK_FactTicket_SLA CHECK (SLAObjetivoHoras > 0),
        CONSTRAINT CK_FactTicket_Voltaje CHECK (VoltajeMinimo < VoltajeMaximo),
        CONSTRAINT CK_FactTicket_Fechas CHECK (FechaCierre IS NULL OR FechaCierre >= FechaApertura),
        CONSTRAINT CK_FactTicket_Estado CHECK (EstadoTicket IN ('Abierto', 'Cerrado'))
    );
END;
GO

IF OBJECT_ID('dbo.AlertaInventarioOutbox', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.AlertaInventarioOutbox
    (
        AlertaInventarioID BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
        EquipoID           VARCHAR(20)    NOT NULL,
        StockAlGenerar     INT            NOT NULL,
        FechaGeneracion    DATETIME2(0)   NOT NULL
            CONSTRAINT DF_AlertaInventarioOutbox_Fecha DEFAULT SYSDATETIME(),
        CorreoEnviadoEn    DATETIME2(0)   NULL,
        UltimoError        NVARCHAR(1000) NULL,
        CONSTRAINT FK_AlertaInventarioOutbox_Equipo FOREIGN KEY (EquipoID)
            REFERENCES dbo.DimEquipo (EquipoID)
    );
END;
GO

CREATE OR ALTER VIEW dbo.vw_AnaliticaComercial
AS
    SELECT
        v.VentaID,
        v.Fecha,
        c.ClienteID,
        c.Nombre AS Cliente,
        c.Sector,
        v.Servicio,
        v.PresupuestoEstimado,
        v.Estado
    FROM dbo.FactVenta AS v
    INNER JOIN dbo.DimCliente AS c ON c.ClienteID = v.ClienteID;
GO

CREATE OR ALTER VIEW dbo.vw_AnaliticaOperativa
AS
    SELECT
        t.TicketID,
        t.FechaApertura,
        t.FechaCierre,
        c.ClienteID,
        c.Nombre AS Cliente,
        c.Sector,
        e.EquipoID,
        e.Nombre AS Equipo,
        e.Categoria,
        e.CostoUnitario,
        t.TipoServicio,
        t.Prioridad,
        t.SLAObjetivoHoras,
        t.VoltajeMedido,
        t.VoltajeMinimo,
        t.VoltajeMaximo,
        t.EstadoTicket,
        CASE
            WHEN t.FechaCierre IS NOT NULL THEN
                CONVERT(BIT, CASE
                    WHEN DATEDIFF(SECOND, t.FechaApertura, t.FechaCierre)
                         <= t.SLAObjetivoHoras * 3600 THEN 1 ELSE 0
                END)
            WHEN DATEDIFF(SECOND, t.FechaApertura, SYSDATETIME())
                 > t.SLAObjetivoHoras * 3600 THEN CONVERT(BIT, 0)
            ELSE CONVERT(BIT, NULL)
        END AS SLA_Cumplido,
        CASE
            WHEN t.VoltajeMedido < t.VoltajeMinimo
              OR t.VoltajeMedido > t.VoltajeMaximo THEN 'ALERTA'
            ELSE 'NORMAL'
        END AS AlertaTension
    FROM dbo.FactTicket AS t
    INNER JOIN dbo.DimCliente AS c ON c.ClienteID = t.ClienteID
    INNER JOIN dbo.DimEquipo AS e ON e.EquipoID = t.EquipoID;
GO

CREATE OR ALTER VIEW dbo.vw_AlertasInventario
AS
    SELECT
        EquipoID,
        Nombre AS Equipo,
        Categoria,
        EsCritico,
        StockActual,
        StockMinimo,
        CostoUnitario,
        CASE
            WHEN StockActual = 0 THEN N'QUIEBRE DE STOCK'
            WHEN StockActual <= StockMinimo THEN N'BAJO MÍNIMO'
            ELSE N'NORMAL'
        END AS EstadoInventario
    FROM dbo.DimEquipo;
GO

CREATE OR ALTER TRIGGER dbo.tr_DimEquipo_GenerarAlertaQuiebre
ON dbo.DimEquipo
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;

    INSERT INTO dbo.AlertaInventarioOutbox (EquipoID, StockAlGenerar)
    SELECT i.EquipoID, i.StockActual
    FROM inserted AS i
    LEFT JOIN deleted AS d ON d.EquipoID = i.EquipoID
    WHERE i.EsCritico = 1
      AND i.StockActual = 0
      AND (d.EquipoID IS NULL OR d.StockActual > 0 OR d.EsCritico = 0);
END;
GO
