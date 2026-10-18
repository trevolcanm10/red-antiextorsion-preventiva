# Fase 3.3 - Aprovisionamiento privado y gestion de cuentas

Estado: gestion privada implementada; la ampliacion aprobada de JWT versionados agrega
users.auth_version mediante migracion incremental 0002. No hay registro publico,
creacion de organizaciones mediante API, eliminacion de cuentas ni traslado
de usuarios entre organizaciones. No agrega CRUD de reportes, alertas o analisis.
El bootstrap no se ejecuta al iniciar la API: requiere una operacion privada explicita.

## Bootstrap de instalacion vacia

Precondiciones: PostgreSQL configurado, revision Alembic 0002 aplicada, las diez tablas
de dominio completamente vacias y consola privada interactiva con entrada oculta.
No se aplica ninguna migracion desde el comando. Un despliegue con datos existentes
no debe intentar vaciarse para satisfacer estas condiciones: bootstrap se negara a operar.
No crea organizaciones adicionales ni recupera credenciales de instalaciones existentes.

Desde backend, por un operador autorizado y en el entorno expresamente seleccionado:

```powershell
& .venv/Scripts/python.exe -m app.cli.bootstrap --organization-name "EMPRESA_AUTORIZADA" --admin-name "ADMINISTRADOR_INICIAL" --admin-email "CORREO_REAL_AUTORIZADO"
```

--organization-type es opcional (hasta 50 caracteres). El comando solicita y confirma
la contrasena con getpass. No existe argumento --password, contrasena predeterminada,
lectura de contrasena desde variables de entorno ni aceptacion de entrada sin terminal.
Si getpass no puede ocultar la entrada, falla cerrado antes de aceptar entrada visible.
No habilita usuarios por el mero hecho de ejecutar --help. La configuracion de DB se
carga solo para la ejecucion explicita, no al importar el modulo.

Una transaccion adquiere pg_advisory_xact_lock(173341, 33), verifica revision 0002 y
consulta las diez tablas. Dos procesos de bootstrap usan la misma clave: solo uno
creara organizacion y administrador. Si se repite con datos, se rechaza sin sobrescribir.
Los dos registros quedan ACTIVO y el usuario recibe ADMINISTRADOR explicitamente,
UUID v4 y hash Argon2id. Cualquier fallo revierte ambos registros. El exito imprime solo
UUID de organizacion y administrador; fallos no imprimen excepciones de DB ni payloads.
Este procedimiento no es un rol global ni un endpoint HTTP.

## Permisos habilitados

Solo ADMINISTRADOR recibe organization.read_self, user.read_others, user.create,
user.change_role, user.deactivate y user.activate. USUARIO/MODERADOR conservan acceso al perfil propio
mediante auth/me. Los administradores no obtienen permisos globales ni herencia de roles.
organization.manage sigue sin grant, al igual que lectura de identidad
del reportante, coordenadas precisas y rutas privadas de evidencia.

Un administrador puede crear los tres roles y cambiar roles de otras cuentas de su
organizacion, incluyendo otros administradores. Nunca cambia su propio rol ni desactiva
su propia cuenta, aun si hay otros administradores. Se permite cambiar roles de cuentas
inactivas; esto no las activa. Ninguna operacion habilita la identidad de autores de reportes.

## Endpoints privados y contratos

Todos requieren JWT vigente, actor ACTIVO y organizacion ACTIVO. La pertenencia y el
rol se consultan en PostgreSQL; los campos de organizacion no se reciben del cliente.

| Metodo/ruta | Contrato | Resultado |
| --- | --- | --- |
| GET /api/v1/organizations/me | Sin body | OrganizationSelfRead |
| GET /api/v1/users | offset >= 0, limit 1..100 (default 50), role/status opcionales | UserPage |
| GET /api/v1/users/{user_id} | UUID | UserManagementRead |
| POST /api/v1/users | name, email, password, role, status, current_password | 201 UserManagementRead |
| PATCH /api/v1/users/{user_id}/role | role, current_password | UserManagementRead |
| PATCH /api/v1/users/{user_id}/status | status=ACTIVO/INACTIVO, current_password | UserManagementRead |

role y status deben ser explicitos en el alta. Se pueden crear cuentas inicialmente
ACTIVO o INACTIVO; las creadas INACTIVO se pueden activar mediante un administrador
autorizado de la misma organizacion, con confirmacion de su contrasena actual.
current_password siempre es la contrasena actual del administrador actuante.
El endpoint status permite desactivar y reactivar otras cuentas. Cualquier operacion
sobre el estado propio esta prohibida; una cuenta inactiva tampoco puede autenticarse
para autorreactivarse. Un cambio al estado actual es idempotente sobre otras cuentas,
pero exige igualmente autorizacion y contrasena actual. ACTIVO -> INACTIVO incrementa
auth_version exactamente una vez. INACTIVO -> ACTIVO no reduce ni reinicia la version.
Cambiar al mismo rol es un noop permitido solo sobre otras cuentas.
No hay PATCH generico de usuarios capaz de modificar contrasena, organizacion o fechas.

name no vacio, recortado, hasta 150 caracteres; email no vacio, recortado, hasta 255.
Se mantiene coincidencia exacta y el UNIQUE global de correo, sin lower/casefold ni
normalizacion automatica de dominio. No se verifica titularidad ni entregabilidad de
correo: el administrador debe validar la identidad en el proceso privado de incorporacion.
La validacion actual preserva la semantica de identificador del login existente.

Contrasenas NUEVAS: 15..1024 caracteres, sin truncamiento, recorte, normalizacion o
reglas de composicion. La confirmacion current_password acepta 1..1024 para permitir
credenciales existentes: no cambia su politica retroactivamente. Se almacenan hashes
Argon2id de pwdlib; el hash codificado cabe en password_hash VARCHAR(255).
SecretStr oculta credenciales en repr. No registrar bodies de endpoints de cuentas. El engine de la aplicacion usa
hide_parameters=True para evitar volcar parametros SQL en logs/excepciones.

Schemas de entrada rechazan campos adicionales: id, organization_id, password_hash,
created_at y last_login no son campos de alta HTTP. La organizacion viene del actor,
UUID/fechas se generan en el servidor. La salida contiene solo id, organization_id,
name, email, role, status, created_at y last_login. UserPage agrega total, offset y limit.
OrganizationSelfRead devuelve id, name, type, status y created_at propios.
No hay contrasenas, hashes, secretos JWT ni relaciones con reportes en esas salidas.
Todas las respuestas de auth, usuarios y organizaciones llevan Cache-Control: no-store.
Los 422 son genericos para no reflejar inputs sensibles, incluidos JSON malformados.

## Transacciones, aislamiento y ultimo administrador

Cada escritura de cuentas realiza, en una unica transaccion READ COMMITTED:

1. Bloqueo SELECT FOR UPDATE de la organizacion autenticada.
2. Relectura del actor con populate_existing, bloqueo de su fila y comprobacion de
   organizacion/estado/rol/permiso actuales DESPUES de esperar el bloqueo. Se compara
   tambien auth_version con la version autenticada que llevaba la peticion antes de esperar.
3. Verificacion de current_password contra el hash vigente.
4. Para actualizaciones: consulta del destinatario por UUID Y organizacion, bloqueo
   de su fila y comprobaciones de autogestion/proteccion del ultimo administrador.
5. INSERT/UPDATE, flush y commit; cualquier fallo hace rollback.

READ COMMITTED se exige en el servicio; se rechaza otro aislamiento para no usar
snapshots anteriores a los commits que ocurren mientras se espera el bloqueo.
No basta el rol leido en la dependencia JWT: puede cambiar mientras la peticion espera.
El bloqueo de organizacion serializa TODOS los escritores de cuentas de esa organizacion.
Antes de desactivar o degradar a un administrador ACTIVO, el servicio exige que quede
al menos otro administrador ACTIVO. Ademas la autodesactivacion/autocambio estan
prohibidos. Dos administradores no pueden desactivarse o degradarse mutuamente dejando
la organizacion sin administrador: el segundo relee su estado/rol actualizado y falla.

La garantia depende de que toda escritura administrativa utilice este protocolo;
SQL privilegiado directo puede saltarse reglas de aplicacion. No se agrega un trigger
ni se cambia el modelo para imponer esta invariante en PostgreSQL. No usar los servicios
con sesiones que contengan escrituras ajenas pendientes: son duenos de commit/rollback.
La autenticacion puede haber abierto la transaccion por autobegin; el servicio la
completa, evitando un begin anidado sobre esa lectura ya iniciada.

Consultas de cuentas/listados/conteos se filtran por organizacion; filtros de role/status
y paginacion no pueden ampliar el alcance. Cuentas ajenas e inexistentes producen 404.
Rol insuficiente/autogestion prohibida: 403. JWT o credenciales de confirmacion invalidos,
actor/organizacion inactivos: 401. Duplicado de correo: 409 generico, sin revelar a que
organizacion pertenece, correo ni nombre de constraint. Otras incompatibilidades: 409.
La unicidad global implica disponibilidad compartida del identificador, no permite
reasignar una cuenta existente ni consultar su organizacion para resolver el conflicto.

## Reactivacion segura y JWT versionados - ampliacion aprobada

Ver [auth-version.md](auth-version.md) para migracion, despliegue y pruebas.
users.auth_version es INTEGER NOT NULL DEFAULT 1, CHECK >= 1. Los usuarios existentes
y nuevos comienzan en 1. No es un campo de entrada ni de consulta publica de cuentas.
JWT lleva ver obligatorio, entero positivo, comparado con PostgreSQL en cada solicitud.
Los JWT anteriores sin ver se rechazan: TODOS los usuarios deberan iniciar sesion de nuevo.

En PATCH status=INACTIVO, la transicion ACTIVO -> INACTIVO incrementa el contador en
la misma transaccion; repetir la desactivacion no suma otra version. Reactivar exige
ADMINISTRADOR activo de la misma organizacion y su contrasena actual. Los tokens
anteriores a la desactivacion no vuelven a ser validos al reactivar. No hay autorreactivacion,
refresh tokens ni blacklist de tokens individuales. Reactivar no restaura ni reinicia
la version; se obtiene un nuevo JWT mediante login. Los cambios de rol no reinician
el contador y el rol continua consultandose desde PostgreSQL.

## Credenciales iniciales y limites de despliegue

Aprovisionamiento privado, controlado y asistido; nunca contrasenas por canales publicos,
logs, respuestas GET/POST, argumentos de proceso o repositorio. El administrador debe
asegurar un canal privado de entrega y verificacion de identidad. Para un despliegue
real faltan invitaciones seguras, eleccion privada y cambio obligatorio de contrasena;
no se simula una contrasena temporal sin caducidad o bandera persistente.
No hay recuperacion automatica de un administrador perdido, organizacion adicional
mediante API, solicitudes pendientes, MFA ni auditoria persistente en nuevas tablas.
Sigue pendiente TLS y proxy real. Ademas de limitar login, deben protegerse los intentos
de confirmacion de contrasena en gestion administrativa frente a abuso. El servicio no
se declara listo para exposicion publica. No crear cuentas reales de forma automatica
para demostrarlo ni ejecutar bootstrap contra la base principal sin una instruccion explicita.

## Pruebas aisladas

ACCOUNTS_TEST_DATABASE_URL debe apuntar exclusivamente a PostgreSQL 16 desechable,
base persistence_test* inicialmente sin tablas de dominio. La suite no toma la URL de
la aplicacion. Aplica 0001 y 0002 en esa instancia; los resets/truncates son
exclusivos de la base aislada. Los casos de concurrencia usan conexiones y transacciones
independientes, barreras/eventos y limites de tiempo. No sustituyen concurrencia real
por sesiones compartidas ni por SQLite. Desde backend:

```powershell
$env:ACCOUNTS_TEST_DATABASE_URL = 'postgresql+psycopg://USUARIO:CLAVE@127.0.0.1:55435/persistence_test_accounts'
& .venv/Scripts/python.exe -B -W error -m unittest tests.test_accounts -v
```

Para toda la suite, apuntar tambien AUTH_TEST_DATABASE_URL,
AUTHORIZATION_TEST_DATABASE_URL y PERSISTENCE_TEST_DATABASE_URL a la misma base
desechable y ejecutar unittest discover secuencialmente. Sin las variables se omiten
pruebas PostgreSQL; eso no constituye validacion completa. Nunca paralelizar suites
que comparten esquema. Todos los usuarios, hashes y secretos de pruebas son sinteticos.


## Validacion inicial de Fase 3.3, anterior a auth_version - 2026-10-18

- 25 pruebas nuevas y 49 existentes: 74 aprobadas, sin omisiones, con advertencias
  tratadas como errores (`python -B -W error -m unittest discover -s tests -v`).
- Concurrencia real verificada: doble bootstrap, altas duplicadas, administradores
  desactivandose/degradandose mutuamente y permisos revocados mientras un escritor espera.
- Rechazo de snapshots no compatibles con el protocolo y rollback de bootstrap parcial.
- Revision 0001 aplicada/revertida exclusivamente en PostgreSQL 16 temporal, tmpfs.
  Alembic check sin diferencias; modelos, migraciones y PDF intactos.
- El bootstrap privado NO se ejecuto contra PostgreSQL principal y no se crearon alli
  organizaciones ni cuentas reales o sinteticas. Sin commit ni push.
