# Persistencia PostgreSQL - modelo inicial

Implementa el modelo logico de diez tablas del Documento Tecnico de Desarrollo,
con las decisiones de implementacion aprobadas en esta fase. Los PDF originales
no se modifican. No se incluyen endpoints, autenticacion ni calculo de riesgo.

## Estructura

- `backend/app/models/`: un modelo por tabla, enumeraciones en `enums.py` y
  constructores compartidos de tipos/FK en `_types.py`.
- `backend/app/schemas/`: cada entidad tiene `Create`, `Read` e `Internal`.
  `Create` valida datos para persistencia, no representa aun un contrato de endpoint.
  `Internal` incluye campos sensibles; no se debe usar como respuesta general.
  `UserCreate` contiene solo metadatos de cuenta; `UserInternal` incorpora el hash
  ya generado por una capa de confianza. Esta fase no recibe contrasenas ni genera hashes.
- `backend/alembic/versions/0001_initial_persistence_model.py`: revision inicial
  autocontenida, sin importar modelos de la aplicacion. Crea y elimina explicitamente
  cinco enums compartidos, diez tablas, restricciones, indices y tres triggers.
- `backend/tests/test_persistence.py`: unittest, sin dependencias de pruebas adicionales.

Tablas: `organizations`, `users`, `locations`, `reports`, `evidence`, `indicators`,
`report_indicators`, `risk_analyses`, `analysis_indicators`, `alerts`.

## Decisiones y garantias

Las PK de entidades principales se generan como UUID v4 en Python. Las asociaciones
utilizan PK compuesta. No hay defaults de rol, estado o nivel. Las fechas son
TIMESTAMPTZ; PostgreSQL conserva instantes y los schemas exigen zona horaria y
normalizan a UTC. La conexion de la aplicacion usa UTC. Las fechas de registro,
creacion, generacion y analisis tienen `now()` del servidor; `detected_at` se
proporciona explicitamente. La zona de presentacion depende de la sesion SQL.

Todas las FK usan ON DELETE RESTRICT y ON UPDATE RESTRICT. Las relaciones ORM no
incluyen delete/delete-orphan; passive_deletes="all" deja la proteccion en PostgreSQL,
incluso cuando las colecciones estan cargadas. Los indices de PK/UNIQUE no se duplican.
La FK compuesta de reports requiere el UNIQUE users(id, organization_id), aunque
id ya sea PK; el indice adicional es necesario para esa referencia compuesta.

La FK reports(user_id, organization_id) impide crear o reasignar reportes a usuarios
de otra organizacion, y tambien impide mover un usuario de organizacion si tiene
reportes existentes. El trigger de reports hace inmutable organization_id. El de
risk_analyses hace inmutable report_id. Ambos aceptan actualizaciones sin cambio de valor.
El trigger de alerts valida INSERT y cambios de analysis_id/organization_id contra
la organizacion del reporte analizado. Si se cambian ambos campos de una alerta,
la nueva pareja debe ser coherente. La cadena comprobada no puede reasignarse
posteriormente porque sus enlaces de pertenencia son inmutables. Las FK protegen
frente a eliminaciones y cambios de PK, incluso concurrentes. No hay actualizaciones
ni eliminaciones en cascada.

Un reporte admite multiples analisis: no hay UNIQUE sobre risk_analyses.report_id.
El catalogo de indicadores y las ubicaciones son compartidos, como en el documento;
no se agregan columnas organization_id. El aislamiento de consultas, acceso a archivos
y permisos corresponden a una fase posterior: los triggers no autorizan lecturas.

## report_indicators

- report_id e indicator_id: identifican una unica asociacion por reporte/indicador.
- value TEXT NULL: observacion o valor de deteccion; puede ser texto, categoria o
  representacion numerica. No se convierte implicitamente a numero.
- confidence NUMERIC(5,4) NULL: confianza entre 0 y 1 inclusive. NULL significa
  desconocida o no calculada, distinto de confianza cero. No es un puntaje de riesgo.
- detected_at TIMESTAMPTZ NOT NULL: instante explicito en que se detecto la senal.

Los tipos y nulabilidad de estos tres atributos complementan la omision del diccionario
original, segun aprobacion. No se incorpora historial de detecciones a esta asociacion.

## Schemas y privacidad

Las respuestas Read no incluyen password_hash, reports.user_id, evidence.file_path,
locations.latitude/longitude ni report_indicators.value. Los schemas son proyecciones
explicitas, sin relaciones anidadas que filtren objetos internos accidentalmente.
Los textos libres pueden contener datos sensibles: la autorizacion y politica de
exposicion de contenido se resolveran antes de publicar endpoints. Internal no debe
serializarse hacia usuarios generales. Las restricciones de longitud, precision,
coordenadas y confianza se validan tambien en Pydantic; no se inventan rangos de pesos,
puntajes ni transiciones de estados.

## Verificacion segura

Antes de ejecutar una migracion contra la base de la aplicacion, inventariar en una
transaccion READ ONLY todos los esquemas, tablas de usuario y alembic_version, y
revisar datos si existen objetos potencialmente afectados. Detenerse y solicitar
aprobacion si hay contenido que pueda resultar afectado. Nunca usar create_all,
stamp para ocultar diferencias, ni borrar/recrear el volumen existente.

Las pruebas solo aceptan una URL PostgreSQL explicita cuya base empiece por
`persistence_test`, inicialmente sin tablas de dominio. Nunca toman la URL de la
aplicacion. Usar una instancia desechable separada. Desde `backend`, en PowerShell:

```powershell
$env:PERSISTENCE_TEST_DATABASE_URL = 'postgresql+psycopg://USUARIO:CLAVE@127.0.0.1:55432/persistence_test'
& .venv/Scripts/python.exe -B -m unittest tests.test_persistence -v
```

La suite verifica upgrade/downgrade/upgrade, limpieza de enums y funciones, ausencia
de diferencias Alembic, SQL offline, FK/UNIQUE/NOT NULL/enums/checks, relaciones ORM,
historial de analisis, privacidad de schemas y aislamiento referencial entre organizaciones.
Cada caso usa datos sinteticos y rollback; al finalizar revierte el esquema de pruebas.
Sin la variable explicita, las pruebas de PostgreSQL se omiten; esto no valida migraciones.
