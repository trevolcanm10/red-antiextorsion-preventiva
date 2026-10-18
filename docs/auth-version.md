# JWT versionados y reactivacion segura

Ampliacion aprobada de Fase 3.3. No agrega roles, tablas ni registro publico. La revision
0001 se conserva intacta. No se han ejecutado migraciones ni bootstrap sobre PostgreSQL
principal: este codigo requiere aplicar 0002 durante un despliegue posterior coordinado.

## Migracion 0002_user_auth_version

Upgrade incremental de 0001 a 0002:
- ADD COLUMN users.auth_version INTEGER NOT NULL DEFAULT 1.
- CHECK auth_version >= 1, con nombre ck_users_auth_version_positive.

El default constante de PostgreSQL rellena los registros existentes con 1 sin reemplazar
usuarios, cambiar ids, hashes, roles, estados ni relaciones. El default permanece para
nuevos INSERT SQL y el ORM usa tambien default=1. No hay campos nuevos aceptados por
los contratos HTTP de alta/gestion, ni se devuelve el contador en perfiles/listados.
No hay UPDATE global de los datos de cuenta ni recreacion de tablas.

El downgrade elimina solo el check/columna nuevos y conserva los registros anteriores,
pero PIERDE la historia de revocacion. No ejecutarlo con la API versionada en servicio,
ni asumir que downgrade/upgrade mantiene invalidados JWT previos. La reversibilidad de
esquema se prueba exclusivamente sobre datos sinteticos en PostgreSQL aislado.

## Contrato JWT

El emisor exige auth_version como argumento explicito, sin fallback/default 1 al emitir.
ver es obligatorio y debe ser un entero positivo estricto: se rechazan bool, float,
cadenas numericas, null, cero y negativos. Se mantienen HS256, firma, iat/exp, issuer,
audience y UUIDs. Claims requeridos: sub, organization_id, iat, exp, iss, aud y ver.

Cada get_current_user consulta el registro actual en PostgreSQL, exige usuario y
organizacion ACTIVO y compara ver == user.auth_version y organization_id vigente.
Una firma valida por si sola no concede acceso. El rol sigue viniendo de la base.
Los tokens sin ver emitidos con el contrato anterior se rechazan con 401, sin una
compatibilidad transitoria que los trate como ver=1. TODOS los usuarios deben volver
a iniciar sesion al desplegar esta version. Los errores no revelan valores de versiones.

## Desactivacion y reactivacion

PATCH /api/v1/users/{user_id}/status conserva el contrato:
{"status":"ACTIVO o INACTIVO","current_password":"CONTRASENA_DEL_ADMINISTRADOR"}.
No se recibe auth_version, version, ver ni organization_id desde el cliente.

Solo ADMINISTRADOR activo de la misma organizacion, con su contrasena vigente, tiene
user.activate y user.deactivate. USUARIO/MODERADOR no pueden activar ni desactivar.
Recursos ajenos/inexistentes: 404. Ningun administrador cambia su propio estado: 403;
una cuenta inactiva no autentica y su intento de autorreactivarse da 401.

La transaccion READ COMMITTED bloquea primero Organization y despues relee/bloquea
actor y destinatario. Recomprueba organizacion activa, rol, estado, permiso y contrasena.
Captura tambien la version del actor autenticado antes de esperar y la compara con
la version releida: una peticion que esperaba mientras se desactivaba/reactivaba al
actor no puede continuar solo porque este vuelve a estar ACTIVO.

- ACTIVO -> INACTIVO: auth_version += 1 y cambio de estado en el mismo flush/commit.
- INACTIVO -> INACTIVO: noop idempotente, sin otro incremento.
- INACTIVO -> ACTIVO: conserva la version incrementada, sin reiniciarla.
- ACTIVO -> ACTIVO: noop sobre otra cuenta, con permisos y confirmacion de contrasena.

Se mantienen prohibicion de autoascenso/autodesactivacion, proteccion del ultimo
administrador activo y aislamiento de organizacion. Todos los escritores de cuentas
comparten el bloqueo de organizacion; SQL privilegiado que omita el protocolo queda
fuera de esta garantia de aplicacion. Un rollback revierte estado Y contador juntos.
Tras reactivar, el usuario necesita nuevo login para obtener un JWT con la version actual.
Esto revoca por usuario, no un JWT individual. No se agregan refresh tokens ni revocacion
selectiva. Los cambios de rol no incrementan el contador, pues cada peticion consulta el rol.

## Carrera entre login y desactivacion

authenticate_user devuelve un principal inmutable con id, organization_id y la version
observada al verificar credenciales. No devuelve un ORM que pueda refrescarse tras commit
y adoptar silenciosamente una version incrementada durante una desactivacion concurrente.
Si la version cambia mientras se completa el login, el JWT conserva la anterior y sera
rechazado: el cliente debe repetir login. No puede ganar una version nueva por un refresh.

## Bootstrap y despliegue posterior

El bootstrap privado exige ahora revision 0002 y las diez tablas vacias; sigue siendo
exclusivamente manual y no recupera ni modifica instalaciones con datos. Crea usuarios
con auth_version=1, sin contrasenas predeterminadas ni operaciones al arrancar la API.
NO se ejecuto el bootstrap sobre la base principal como parte de esta tarea.

Para un despliegue posterior: coordinar parada de trafico/API anterior, respaldo y
verificacion del estado de la base, aplicar exclusivamente upgrade 0002 por el operador,
y arrancar la API actualizada. No desplegar este codigo sobre un esquema 0001. Comunicar
antes la necesidad de volver a iniciar sesion. La presente tarea no ejecuta esos pasos
contra la base principal. Mantener TLS, limites del proxy y los pendientes de invitaciones
seguras/cambio obligatorio de contrasena descritos en accounts.md; no se declara listo
para exposicion publica.

## Verificacion aislada

Todas las suites requieren URLs explicitas a PostgreSQL de pruebas persistence_test*,
sin fallback a la configuracion principal. La suite de migracion inicia en 0001 con
datos sinteticos relacionados en las diez tablas, comprueba el upgrade/backfill y
compara los datos previos completos. Comprueba tambien defaults de nuevos usuarios,
restricciones, downgrade/upgrade y ausencia de diferencias con metadata Alembic.

Variables para ejecutar toda la suite secuencialmente sobre una instancia desechable:
ACCOUNTS_TEST_DATABASE_URL, AUTH_TEST_DATABASE_URL, AUTHORIZATION_TEST_DATABASE_URL,
PERSISTENCE_TEST_DATABASE_URL y AUTH_VERSION_TEST_DATABASE_URL. Desde backend:

```powershell
& .venv/Scripts/python.exe -B -W error -m unittest discover -s tests -v
```

Sin esas variables se omiten pruebas SQL/HTTP; no equivale a validacion completa.
No paralelizar suites que comparten base. Las carreras usan conexiones independientes,
barreras/eventos y timeouts, sin modificar ni montar el volumen PostgreSQL principal.


## Resultado de validacion - 2026-10-18

85 pruebas aprobadas, sin omisiones, con advertencias tratadas como errores. Incluyen
las 74 anteriores adaptadas al nuevo contrato y 11 adicionales de migracion, tokens,
rollback y concurrencia. Se verifico el paso real 0001 -> 0002 sobre datos sinteticos
en las diez tablas y ausencia de diferencias Alembic/metadata. Tambien se verifico SQL
offline y la reversibilidad exclusivamente en pruebas (con la limitacion documentada
de perdida del contador al hacer downgrade). git diff --check correcto.

PostgreSQL 16 temporal con tmpfs, separado de la instancia/volumen principal.
No se ejecutaron migraciones ni bootstrap sobre PostgreSQL principal. No se modifico
0001 ni los PDF. Sin commit ni push. La aplicacion de 0002 en la base principal y la
coordinacion del nuevo login de todos los usuarios quedan para un despliegue posterior.
