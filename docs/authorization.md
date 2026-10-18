# Fase 3.2 - Autorizacion por accion y recurso

> Actualizacion Fase 3.3: el alcance historico de esta fase se amplia en
> [accounts.md](accounts.md). Ahora existen rutas privadas de gestion de cuentas y
> permisos administrativos explicitos. La ampliacion aprobada [auth-version.md](auth-version.md)
> habilita reactivacion segura con auth_version y migracion 0002. Las restricciones de privacidad y organizacion siguen vigentes.

Implementa permisos en codigo, politicas, consultas de alcance y dependencias FastAPI.
No agrega roles, tablas, migraciones ni endpoints CRUD. La unica ruta productiva
conectada al catalogo es GET /api/v1/auth/me (profile.read). Login permanece igual.
Los probes HTTP de las pruebas viven en otra aplicacion FastAPI, nunca en app.main.

## Capas y archivos

- app/core/permissions.py: Permission, ROLE_PERMISSIONS inmutable, has_permission.
  Los tres roles tienen grants explicitos; no hay herencia ni superadministrador.
  Una accion desconocida o sin grant se deniega, tambien para ADMINISTRADOR.
- app/services/authorization.py: politicas de organizacion, autor y estado;
  no realiza escrituras. Sus excepciones son independientes de FastAPI.
- app/repositories/access.py: scopes SQL y loaders de lectura, sin mutaciones.
- app/api/dependencies.py: require_permission y traduccion segura de errores.
  Reutiliza get_current_user para consultar estado y rol actuales en PostgreSQL.
- app/api/access.py: require_report, require_alert, require_evidence,
  require_analysis y require_alert_transition. No registra rutas.
- app/schemas/access.py y services/access_views.py: proyecciones limitadas con
  autorizacion previa. No usar los schemas internos como respuestas publicas.
- tests/test_authorization.py: politicas y probes HTTP con PostgreSQL aislado.

## Matriz aprobada e implementada

Todas las acciones requieren usuario ACTIVO y organizacion ACTIVO. Ningun permiso
concede acceso fuera de la organizacion del actor autenticado.

| Accion | USUARIO | MODERADOR | ADMINISTRADOR |
| --- | --- | --- | --- |
| profile.read | Perfil propio | Perfil propio | Perfil propio |
| report.create | Si | Si explicito | Si explicito |
| report.read | Propios | Organizacion | Organizacion |
| report.edit / evidence.attach | Autor, REGISTRADO | Autor, REGISTRADO | Autor, REGISTRADO |
| evidence.read | Segun acceso al reporte | Organizacion | Organizacion |
| report.review | No | Organizacion, no propios | Organizacion, no propios |
| report.close | No | ANALIZADO, no propios | ANALIZADO, no propios |
| analysis.read_summary | Reportes propios | Organizacion | Organizacion |
| analysis.read_detail | No | Organizacion | Organizacion |
| alert.read_preventive | Organizacion, vista limitada | Organizacion | Organizacion |
| alert.read_detail | No | Organizacion, vista autorizada | Organizacion, vista autorizada |
| alert.attend / alert.close | No | Organizacion, transicion valida | Organizacion, transicion valida |

El permiso report.review representa elegibilidad para revision, sin validar ni observar,
y no altera estados. No se equipara ANALIZADO a VALIDADO. El permiso por si solo no
es una operacion ni genera resultados de moderacion. No se ha aprobado una restriccion
adicional de estado para consultar/revisar; no se inventa una equivalencia de estados.
La clausura administrativa solo es elegible desde ANALIZADO y excluye reportes propios,
conforme a la matriz aprobada. No hay reapertura de reportes ni actualizacion generica
de su estado. Alertas: solo ACTIVA -> ATENDIDA y ATENDIDA -> CERRADA. No se aceptan
saltos, reaperturas ni transiciones al mismo estado. Las funciones solo comprueban;
la escritura y closed_at se resolveran al implementar endpoints futuros.

## Acciones bloqueadas para todos

report.validate, report.observe, reporter_identity.read, precise_location.read,
evidence_path.read, user.read_others, user.create, user.change_role, user.deactivate,
organization.manage, resource.delete, analysis.write y alert.create no tienen grants.
Registrar una constante bloqueada no habilita la funcionalidad. No se habilita gestion
de usuarios hasta definir las reglas de alta, promocion, cambios de rol y desactivacion.
No hay creacion manual de alertas o resultados de analisis por roles humanos.
La futura logica interna necesitara su propio punto de entrada controlado, no un grant
publico ni un bypass de organizacion para administradores.

## Alcance por organizacion y propiedad

No confiar en organization_id/user_id aportados por el cliente. Reportes nuevos deberan
recibir esos identificadores del actor autenticado. Los futuros contratos HTTP deben
excluir ids de pertenencia, estado inicial y fechas de servidor; los actuales schemas
Create de persistencia no deben usarse directamente como contratos de endpoints.

reports_query y report_scope aplican siempre organization_id del actor y, para lecturas
de USUARIO, su user_id. Editar/adjuntar exige autor para cualquier rol. alerts_query
filtra por organizacion. En listados, filtros adicionales, paginacion y conteos deben
aplicarse a estas consultas ya acotadas, nunca a una consulta global. Estos scopes
acotan organizacion/propiedad; no sustituyen la comprobacion de estado de la politica.
Para operaciones por objeto usar los loaders, no solamente has_permission/scopes SQL.

load_report/load_alert verifican el permiso y el alcance antes de devolver el objeto,
y aplican la politica de estado. load_evidence/load_analysis hacen JOIN con Report y
comprueban simultaneamente el padre indicado y el identificador hijo. Conocer el UUID
de una evidencia, analisis o alerta no concede acceso al reporte vinculado. En particular,
USUARIO puede ver una alerta preventiva de su organizacion sin poder consultar el reporte
ajeno o analisis que la origino. Las ubicaciones compartidas no tienen endpoint directo;
no se concede permiso para ver coordenadas ni modificarlas como recurso independiente.

Respuestas de error:
- 401: autenticacion ausente/invalida, usuario u organizacion no habilitados.
- 403: rol sin la accion solicitada, revision/cierre administrativo propios.
- 404 generico: recurso inexistente, de otra organizacion, fuera del alcance por autor
  o relacion padre/hijo incorrecta. No consultar globalmente para distinguir los casos.
- 409 generico: actor autorizado, recurso visible pero estado incompatible.

has_permission es solo una consulta al catalogo; no reemplaza ensure_permission o las
politicas por recurso. require_roles queda disponible como helper de roles exactos,
sin jerarquia. require_organization conserva su semantica previa de 403 para un contexto
de organizacion explicito; los loaders por recurso usan 404 para ocultar existencia.

## Privacidad de respuestas

AlertPreventiveRead solo contiene id, level, status y generated_at.
AlertAuthorizedDetailRead agrega organization_id, analysis_id y closed_at. El detalle
no habilita automaticamente lectura del recurso vinculado: cada acceso lo autoriza su
propia politica. No se incluye identidad del reportante ni coordenadas/rutas internas.
Por denegacion por defecto tampoco se proyectan title/message de alertas: son textos
libres que pueden contener identidad o datos sensibles; su exposicion segura necesita
un contrato de contenido definido. Esto preserva una vista limitada util sin inventar
un mecanismo de anonimizado. Las proyecciones son deliberadamente conservadoras.
AnalysisSummaryRead contiene id, report_id, risk_level y analyzed_at; no justificacion.

Las dependencias devuelven objetos ORM internos para uso del servicio, no respuestas
listas para serializar. No devolverlos directamente a clientes. Usar los view helpers
y response_model adecuados. El permiso analysis.read_detail prepara la autorizacion,
pero la proyeccion de sus textos libres aun debe definirse antes de exponer endpoints.
Los schemas genericos AlertRead/RiskAnalysisRead de persistencia no sustituyen las
proyecciones autorizadas. Ningun rol recibe grants de lectura de campos sensibles.
Los textos libres y el contenido de archivos no quedan anonimizados por quitar campos:
se mantiene pendiente su politica de exposicion antes de publicar los CRUD.

## Uso futuro y concurrencia

Ejemplo de dependencia: Depends(require_report(Permission.REPORT_EDIT)). Los nombres
de parametros deben coincidir con report_id, alert_id, evidence_id y analysis_id.
require_evidence y require_analysis esperan tambien report_id para la relacion anidada.
require_alert_transition solo acepta ATENDIDA o CERRADA como destino configurado.

No se implementa CRUD en esta fase. Al escribir, ejecutar la politica nuevamente dentro
de la transaccion con bloqueo del reporte/alerta o UPDATE condicionado por organizacion,
autor y estado esperado; comprobar filas afectadas. La autorizacion previa de una
peticion no es un bloqueo de concurrencia. Los schemas de actualizacion permitiran
solo campos de contenido autorizados, sin reasignar autor, organizacion o estados por
un PATCH generico. No habilitar cambios de rol mediante la actualizacion de perfil.

## Pruebas aisladas

Solo datos sinteticos y PostgreSQL 16 temporal, sin el volumen principal. La variable
AUTHORIZATION_TEST_DATABASE_URL es obligatoria para los probes HTTP/SQL, y debe nombrar
una base persistence_test* inicialmente sin tablas de dominio. Se aplica/revierte solo
la revision existente 0001. Cada caso revierte su transaccion. Desde backend:

```powershell
$env:AUTHORIZATION_TEST_DATABASE_URL = 'postgresql+psycopg://USUARIO:CLAVE@127.0.0.1:55434/persistence_test_authorization'
& .venv/Scripts/python.exe -B -W error -m unittest tests.test_authorization -v
```

Sin esa variable se omiten las pruebas PostgreSQL: no equivale a validacion completa.
AUTH_TEST_DATABASE_URL y PERSISTENCE_TEST_DATABASE_URL pueden apuntar al mismo contenedor
desechable para ejecutar todas las suites secuencialmente. No paralelizarlas contra la
misma base. Los tokens/secrets/usuarios de pruebas son sinteticos y no se guardan en .env.

## Decisiones pendientes y alcance posterior

- Representacion de resultados de validacion/observacion y observaciones de moderacion;
  no existen campos/estados correspondientes en el modelo aprobado.
- Destinatarios y contratos para identidad, coordenadas precisas y archivos privados.
- Contenido seguro de titulos/mensajes de alerta y detalle de analisis.
- Altas, promociones, cambios de rol, desactivaciones y proteccion del ultimo administrador.
- Auditoria persistente, endpoints de recursos y aplicacion transaccional de las politicas.
- Sigue pendiente el despliegue de TLS/proxy limitador descrito en authentication.md;
  esta fase no declara el servicio listo para exposicion publica.


## Validacion realizada - 2026-10-18

- 19 pruebas nuevas de autorizacion y 30 existentes: 49 aprobadas, sin omisiones,
  con advertencias tratadas como errores (`python -B -W error -m unittest discover -s tests -v`).
- PostgreSQL 16 en contenedor temporal independiente con almacenamiento tmpfs.
  Las tres suites usaron exclusivamente la revision 0001 en esa instancia de pruebas.
- Alembic check sin diferencias entre modelos y esquema. git diff --check correcto.
- Sin operaciones sobre PostgreSQL principal. Modelos, migraciones y PDF intactos.
- Ningun endpoint CRUD productivo agregado; /auth/me utiliza ahora profile.read.
