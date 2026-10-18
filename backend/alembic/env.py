from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from app.core.config import get_settings
from app.db.base import Base
import app.models  # noqa: F401 - register every mapped table

# Este es el objeto Config de Alembic, que da acceso a los
# valores del archivo .ini en uso.
config = context.config

# La URL de la base de datos se obtiene desde la configuracion de la
# aplicacion (Pydantic Settings), no se hardcodea aqui.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))

# Interpreta el archivo de configuracion para el logging de Python.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata de la Base declarativa para soportar migraciones autogeneradas.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Ejecuta migraciones en modo 'offline'.

    Configura el contexto solo con la URL, sin crear un Engine, por lo que
    incluso no hace falta un driver DBAPI disponible.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Ejecuta migraciones en modo 'online'.

    Crea un Engine y asocia una conexion con el contexto.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
