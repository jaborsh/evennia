"""
Add JSON value storage to Attributes.

JSON-representable values are stored in the new `db_json` column (jsonb on
PostgreSQL) instead of the pickled `db_value` column, flagged by
`db_storage_type`. Existing rows default to 'pickle' and keep working
unchanged; the `convert_attribute_storage` management command can convert
them in bulk.

"""

from django.db import migrations, models

import evennia.utils.picklefield


class Migration(migrations.Migration):
    dependencies = [
        ("typeclasses", "0017_use_index_instead_of_index_together_in_tags"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attribute",
            name="db_value",
            field=evennia.utils.picklefield.PickledObjectField(
                help_text=(
                    "The data returned when the attribute is accessed. Must be "
                    "written as a Python literal if editing through the admin "
                    "interface. Attribute values which are not Python literals "
                    "cannot be edited through the admin interface. Only used when "
                    "db_storage_type is 'pickle'; JSON-representable values are "
                    "stored in db_json instead."
                ),
                null=True,
                verbose_name="value",
            ),
        ),
        migrations.AddField(
            model_name="attribute",
            name="db_json",
            field=models.JSONField(
                blank=True,
                help_text=(
                    "JSON storage for the attribute value (used when db_storage_type "
                    "is 'json'). Types JSON cannot represent natively are wrapped in "
                    "reserved single-key dicts like '__tuple__' or '__dbobj__' - see "
                    "evennia.utils.dbserialize."
                ),
                null=True,
                verbose_name="json value",
            ),
        ),
        migrations.AddField(
            model_name="attribute",
            name="db_storage_type",
            field=models.CharField(
                choices=[("pickle", "pickle"), ("json", "json")],
                default="pickle",
                help_text=(
                    "Which column holds this Attribute's value: 'pickle' (db_value) "
                    "or 'json' (db_json)."
                ),
                max_length=8,
                verbose_name="storage type",
            ),
        ),
    ]
