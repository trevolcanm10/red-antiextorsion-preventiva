# 🛡️ Red Antiextorsión Preventiva

Plataforma privada orientada a empresas de transporte público para apoyar la **prevención y respuesta temprana frente a amenazas de extorsión**, desarrollada para **WarriorHacks 2.0**.

## 📌 Problema

Las amenazas de extorsión pueden llegar a diferentes miembros de una empresa de transporte mediante llamadas, mensajes u otros medios.

Esta información suele permanecer dispersa entre trabajadores, dispositivos y canales de comunicación, dificultando identificar relaciones entre incidentes y organizar oportunamente una respuesta preventiva.

## 💡 Solución

**Red Antiextorsión Preventiva** propone una plataforma privada donde usuarios autorizados pueden registrar amenazas e incidentes de manera segura.

El sistema procesa la información registrada para:

- Identificar indicadores relevantes.
- Relacionar reportes con características comunes.
- Evaluar niveles de riesgo.
- Generar alertas preventivas.
- Facilitar el seguimiento de incidentes.
- Apoyar la toma de medidas preventivas dentro de la organización.

La plataforma busca complementar las tecnologías y mecanismos de seguridad existentes. No pretende identificar delincuentes, predecir delitos ni sustituir el trabajo de las autoridades.

## 🎯 MVP

El MVP está enfocado en demostrar el siguiente flujo:

```text
Registro de reporte
        ↓
Procesamiento
        ↓
Detección de indicadores
        ↓
Correlación de información
        ↓
Evaluación del riesgo
        ↓
Generación de alertas
        ↓
Respuesta preventiva
```

Entre las funcionalidades principales se contemplan:

- Autenticación y acceso restringido.
- Registro privado de reportes.
- Consulta y seguimiento de reportes.
- Revisión y validación de información.
- Análisis preventivo.
- Evaluación de niveles de riesgo.
- Alertas internas.
- Panel preventivo.
- Mapa preventivo.

## 🏗️ Arquitectura

La aplicación utiliza una arquitectura web separando frontend, backend y persistencia de datos.

```text
┌─────────────────────┐
│      Frontend       │
│ Next.js + React + TS│
└──────────┬──────────┘
           │ API REST
           ▼
┌─────────────────────┐
│       Backend       │
│ Python + FastAPI    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│     PostgreSQL      │
└─────────────────────┘
```

El backend sigue una arquitectura en capas utilizando **Service Layer** y **Repository Pattern** para separar la API, lógica de negocio y acceso a datos.

## 🧰 Tecnologías

### Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS

### Backend

- Python
- FastAPI
- SQLAlchemy
- Alembic
- Pydantic

### Base de datos

- PostgreSQL

### Seguridad

- JWT
- Autorización basada en roles
- Hashing de contraseñas
- Control de acceso por organización

### Infraestructura

- Docker
- Docker Compose
- Git
- GitHub

## 📁 Estructura del proyecto

```text
red-antiextorsion-preventiva/
│
├── backend/
├── frontend/
├── docs/
│   ├── planificacion-warriorhacks2.pdf
│   └── documento-tecnico-desarrollo.pdf
│
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

## 📚 Documentación

La carpeta `docs/` contiene la documentación utilizada para definir y desarrollar el proyecto:

- **Planificación WarriorHacks 2.0:** problema, propuesta, alcance, arquitectura, MVP, navegación e interfaces.
- **Documento Técnico de Desarrollo:** stack tecnológico, base de datos, backend, API REST, seguridad, frontend, análisis preventivo, pruebas y despliegue.

## 🔐 Roles

El MVP contempla tres niveles principales de acceso:

- **Usuario:** registra y consulta información autorizada.
- **Moderador:** revisa y valida reportes.
- **Administrador:** administra usuarios y funciones de la red privada.

## 🚀 Ejecución

> ⚠️ El proyecto se encuentra actualmente en desarrollo.

Las instrucciones para ejecutar el sistema mediante Docker Compose serán incorporadas cuando se complete la configuración inicial del frontend, backend y PostgreSQL.

## 🧪 Estado del proyecto

🚧 **En desarrollo — MVP para WarriorHacks 2.0**

Actualmente se está trabajando en la implementación del sistema a partir del diseño técnico definido en la documentación.

## 🏆 Hackathon

Proyecto desarrollado para **WarriorHacks 2.0**.

**Track:** Hackathon Track  
**Objetivo:** desarrollar una solución tecnológica funcional que contribuya a resolver un problema relevante para la comunidad.

---

> La finalidad de Red Antiextorsión Preventiva es apoyar la organización, prevención y priorización de información frente a posibles amenazas, no determinar la existencia de un delito ni sustituir a las autoridades competentes.
