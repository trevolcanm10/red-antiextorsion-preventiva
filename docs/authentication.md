# Fase 3.1 - Autenticacion privada

Implementa POST /api/v1/auth/login y GET /api/v1/auth/me. No agrega tablas,
columnas ni migraciones. No hay registro publico de usuarios, administradores u
organizaciones. No se implementa aprovisionamiento de cuentas, solicitudes de acceso,
recuperacion/cambio de contrasena, frontend ni CRUD de recursos.

## Configuracion y arranque

Instalar `backend/requirements.txt`; para pruebas, `backend/requirements-dev.txt`.
Configurar en el entorno o .env (sin versionarlo):

- JWT_SECRET: obligatorio, generado aleatoriamente, minimo 32 bytes; no hay default.
- JWT_ACCESS_TOKEN_MINUTES: entero positivo, default 15.
- JWT_ISSUER: default red-antiextorsion-preventiva.
- JWT_AUDIENCE: default red-antiextorsion-api.

El algoritmo es exclusivamente HS256, fijado en el servidor, nunca elegido por el
cliente. El secreto no se imprime. Guardarlo en un gestor de secretos al desplegar.
La validacion minima de longitud no puede comprobar su aleatoriedad: no usar frases,
valores de ejemplo ni repetir caracteres. Generarlo y provisionarlo mediante un canal
privado. La API valida la configuracion al arrancar; Alembic no requiere JWT_SECRET.
No se modifica automaticamente el .env existente. Es necesario configurar el secreto
antes de iniciar Uvicorn. Desde backend, para uso local:

```powershell
& .venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

## Contratos

POST /api/v1/auth/login, Content-Type application/json:

```json
{"email":"persona@example.invalid","password":"CONTRASENA_DEL_USUARIO"}
```

200: {"access_token":"<JWT>","token_type":"bearer","expires_in":900}.
expires_in refleja la configuracion efectiva en segundos. Solo este endpoint devuelve
el token; nunca un hash ni el secreto de firma. Los campos adicionales se rechazan.
El correo es una cadena no vacia de hasta 255 caracteres. No se introduce normalizacion
que difiera del modelo persistente. La contrasena acepta 1 a 1024 caracteres como limite
tecnico de entrada, no como politica de alta de cuentas; no se recorta ni normaliza.
SecretStr oculta la contrasena en repr. Los errores HTTP 422 son genericos para no
reflejar datos de entrada, incluso JSON malformado. Ningun manejador registra el body,
Authorization ni tokens. No habilitar logs de depuracion con credenciales.

GET /api/v1/auth/me requiere Authorization: Bearer <JWT>.
200 devuelve solo id, organization_id, name, email, role y status propios.
No devuelve perfiles de terceros ni permite seleccionar organizacion por parametro.
Las respuestas de ambos endpoints, incluidos errores, usan Cache-Control: no-store.

401 (WWW-Authenticate: Bearer): credenciales incorrectas, cuenta no habilitada,
Bearer ausente/invalido/expirado, usuario eliminado u organizacion del token desactualizada.
El login no diferencia correo inexistente, contrasena incorrecta, usuario inactivo u
organizacion inactiva. 403: usuario autenticado sin el rol o la organizacion requeridos.
422: entrada invalida, con detalle generico sin reproducir valores.

## Hashing, tokens y autorizacion

pwdlib[argon2] usa Argon2id recomendado: memoria 65536 KiB, tres iteraciones,
paralelismo cuatro, salt individual aleatorio. El hash codificado cabe en VARCHAR(255).
verify_and_update permite actualizar parametros al completar un login valido.
Hashes desconocidos fallan cerrados; no se transforman contrasenas ni se acepta texto
plano como hash. Un hash ficticio calentado al arrancar permite verificar tambien
intentos de correos inexistentes; esto reduce diferencias temporales, sin prometer
que todos los caminos de autenticacion tarden exactamente lo mismo.

Tras login valido se actualiza last_login en UTC y, si procede, el hash, en la misma
transaccion. No se modifica last_login ante fallos ni por consultar /me.
Los claims obligatorios son sub (UUID), organization_id (UUID), iat, exp, iss y aud.
Se verifican firma, algoritmo permitido, emisor, audiencia, tipos, orden de fechas
y expiracion sin tolerancia adicional. No se incluyen password, hash, correo o rol.
Los JWT estan firmados, no cifrados; no se deben colocar datos sensibles en ellos.

get_current_user consulta PostgreSQL en cada peticion protegida: usuario ACTIVO y
organizacion ACTIVO. ACTIVO es la representacion disponible de organizacion autorizada.
El rol viene siempre de PostgreSQL; un claim role adicional no concede privilegios.
El organization_id del token debe coincidir con la pertenencia vigente del usuario.
Un token anterior al traslado de organizacion deja de ser aceptado.

require_roles utiliza listas exactas; ADMINISTRADOR no hereda permisos de MODERADOR.
require_organization comprueba la organizacion incluso para administradores. Las futuras
rutas de recursos deben utilizar estas dependencias y filtrar sus consultas por la
organizacion autenticada. La autenticacion no reemplaza el aislamiento de consultas;
esta fase solo expone el perfil propio y prueba los controles con rutas de prueba.

Decision provisional aprobada: quitar solo espacios externos del correo y comparar
exactamente, distinguiendo mayusculas. No usar lower/casefold ni reinterpretar cuentas.
El aprovisionamiento futuro debe respetar esta regla hasta que se acuerde otra politica.

## Proxy e intentos de login: pendiente de despliegue

El Compose actual contiene solo PostgreSQL. NO hay un proxy activo ni un limitador de
login en FastAPI. El login NO esta listo para exposicion publica.
`deploy/nginx/auth-reference.conf` es una referencia local, no esta habilitada por Compose.
Define Nginx a 5 solicitudes por minuto por IP de conexion, con respuesta 429; aplica
a todos los intentos, exitosos o no. Es un leaky bucket sin burst, aproximadamente
una solicitud cada 12 segundos: no ofrece cinco intentos simultaneos ni es un contador
exacto de ventanas de 60 segundos. Los usuarios tras NAT comparten el limite.

La clave es $binary_remote_addr. No se usa X-Forwarded-For, X-Real-IP o Forwarded
enviados por el cliente para identificarlo. Nginx sobrescribe/elimina esas cabeceras
antes de reenviar. No hay real_ip_header ni set_real_ip_from en esta referencia.
El access log evita cuerpos, Authorization y query strings. No transmitir tokens
mediante URL. La variante de login con barra final redirige a la ruta limitada.

La referencia escucha solo en loopback y usa HTTP local. Para exponer el sistema:
configurar TLS, mantener el puerto del backend inaccesible desde Internet y habilitar
el limite en el proxy real. Se puede conservar --no-proxy-headers: la aplicacion no
necesita la IP reenviada para autenticar. Si se necesita procesar cabeceras del proxy,
permitir unicamente las IP concretas del proxy en Uvicorn; nunca usar confianza global.
Si existe un balanceador/CDN anterior a Nginx, adaptar la topologia y confiar solo en
sus rangos verificados mediante controles de red antes de habilitar real_ip. No copiar
esta referencia como si identificara correctamente clientes detras de otro proxy.
No ofrece defensa distribuida, bloqueo de cuentas ni auditoria persistente.

## Limitaciones de sesiones

No hay refresh token, blacklist, revocacion individual ni logout de servidor. Un token
robado funciona hasta expirar si usuario y organizacion siguen habilitados; cambiar
la contrasena no lo invalida. Desactivar cuenta/organizacion tiene efecto en la siguiente
peticion. Los roles cambian en la siguiente peticion sin volver a iniciar sesion.
Rotar JWT_SECRET invalida todos los tokens, no permite revocacion selectiva.
No se define todavia una politica de contrasenas nuevas, altas, recuperacion o MFA.

## Pruebas aisladas

Usar PostgreSQL 16 desechable sin montar el volumen principal. La suite exige
AUTH_TEST_DATABASE_URL explicita, nombre de base persistence_test* y ausencia inicial
de tablas de dominio. Nunca toma la URL de la aplicacion. Aplica exclusivamente la
revision existente 0001 en esa instancia y la revierte al terminar. Cada prueba usa
datos sinteticos dentro de una transaccion que se revierte. Desde backend:

```powershell
$env:AUTH_TEST_DATABASE_URL = 'postgresql+psycopg://USUARIO:CLAVE@127.0.0.1:55433/persistence_test_auth'
& .venv/Scripts/python.exe -B -m unittest tests.test_auth -v
```

Sin esa variable, las pruebas HTTP/PostgreSQL se omiten; solo se ejecutan pruebas
unitarias y eso no constituye validacion completa. Para ejecutar ademas persistencia,
PERSISTENCE_TEST_DATABASE_URL puede apuntar a la misma instancia desechable: cada suite
exige y deja el esquema de dominio vacio. No ejecutar suites en paralelo contra esa base.

Referencias: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
https://frankie567.github.io/pwdlib/reference/pwdlib/
https://pyjwt.readthedocs.io/en/latest/api.html
https://nginx.org/en/docs/http/ngx_http_limit_req_module.html


## Validacion realizada - 2026-10-18

- 15 pruebas nuevas de autenticacion y 15 de persistencia: 30 aprobadas, sin omisiones,
  con advertencias tratadas como errores (`python -B -W error -m unittest discover -s tests -v`).
- PostgreSQL 16 en contenedor separado con almacenamiento tmpfs; solo se uso 0001.
- Alembic check sin diferencias entre metadata y esquema de pruebas.
- Nginx: `nginx -t` correcto en contenedor temporal sin red. Esta es validacion de
  sintaxis, no un despliegue ni una prueba de limitacion sobre trafico publico.
- pwdlib 0.3.1 y PyJWT 2.15.1 verificados. Para el TestClient de la version instalada
  de Starlette se usa httpx2 2.13.1, evitando su compatibilidad obsoleta con httpx.
- Ninguna operacion contra PostgreSQL principal; modelos, revision 0001 y PDF intactos.
