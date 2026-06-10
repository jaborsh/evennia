"""
Add a GIN index on Attribute.db_json for PostgreSQL.

The index accelerates jsonb containment queries (`@>`, `@?`, `@@`) against
attribute values, e.g. finding all objects whose attribute references a
given dbobject. `jsonb_path_ops` is used over the default `jsonb_ops` as it
is smaller and faster for containment, which is the only operator class we
need. Uses raw SQL (rather than django.contrib.postgres.GinIndex) so games
need no extra INSTALLED_APPS; on other database backends this migration is
a no-op.

"""

from django.db import migrations

INDEX_NAME = "typeclasses_attribute_db_json_gin"


def add_gin_index(apps, schema_editor):
    """
    Create the GIN index on PostgreSQL only.

    Args:
        apps (StateApps): Historical app registry (unused).
        schema_editor (BaseDatabaseSchemaEditor): The active schema editor.

    """
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(
        f'CREATE INDEX IF NOT EXISTS "{INDEX_NAME}" ON "typeclasses_attribute" '
        f'USING gin ("db_json" jsonb_path_ops)'
    )


def drop_gin_index(apps, schema_editor):
    """
    Drop the GIN index on PostgreSQL only (reverse operation).

    Args:
        apps (StateApps): Historical app registry (unused).
        schema_editor (BaseDatabaseSchemaEditor): The active schema editor.

    """
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f'DROP INDEX IF EXISTS "{INDEX_NAME}"')


class Migration(migrations.Migration):
    dependencies = [
        ("typeclasses", "0018_attribute_json_storage"),
    ]

    operations = [
        migrations.RunPython(add_gin_index, drop_gin_index),
    ]
