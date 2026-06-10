"""
Convert pickle-stored Attribute values to JSON storage where possible.

New and updated Attributes automatically store JSON-representable values in
the `db_json` column; this command upgrades pre-existing pickle rows in bulk.
Rows whose values have no JSON representation (custom classes, bytes etc) are
left as pickle - that is their permanent storage, not an error.

Run with the server stopped: the server's model cache will not see direct
database writes and could overwrite them on save.

"""

from django.core.management.base import BaseCommand
from django.db import transaction

from evennia.typeclasses.attributes import Attribute
from evennia.utils.dbserialize import (
    JSON_STORAGE_TYPE,
    PICKLE_STORAGE_TYPE,
    VALUE_STORAGE_FIELDS,
    NotJSONSerializable,
    to_jsonable,
)


class Command(BaseCommand):
    """
    Management command converting pickle-stored Attributes to JSON storage.

    """

    help = (
        "Convert pickle-stored Attribute values to JSON storage where "
        "possible. Values with no JSON representation stay as pickle. "
        "Idempotent; run with the server stopped."
    )

    def add_arguments(self, parser):
        """
        Add command-line options.

        Args:
            parser (ArgumentParser): The command's argument parser.

        """
        parser.add_argument(
            "--batchsize",
            type=int,
            default=500,
            help="Number of Attributes to process per database batch (default 500).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be converted without writing to the database.",
        )

    def handle(self, *args, **options):
        """
        Run the conversion in pk-cursor batches.

        Args:
            *args: Unused positional arguments.
            **options: Parsed command-line options.

        """
        batchsize = options["batchsize"]
        dry_run = options["dry_run"]

        converted_count = 0
        kept_pickle_count = 0
        failed_count = 0
        batch_count = 0
        last_id = 0

        while True:
            batch = list(
                Attribute.objects.filter(
                    db_storage_type=PICKLE_STORAGE_TYPE, id__gt=last_id
                ).order_by("id")[:batchsize]
            )
            if not batch:
                break
            batch_count += 1
            last_id = batch[-1].id

            converted = []
            for attr in batch:
                try:
                    # the field already unpickled db_value to the intermediate form
                    intermediate = attr.db_value
                    if intermediate is None:
                        # None (and legacy strvalue rows) stay on the pickle path
                        kept_pickle_count += 1
                        continue
                    attr.db_json = to_jsonable(intermediate)
                except NotJSONSerializable:
                    kept_pickle_count += 1
                except Exception as err:
                    # e.g. stale pickle blobs referencing moved/renamed classes
                    failed_count += 1
                    self.stderr.write(f"Could not load Attribute #{attr.id}: {err}")
                else:
                    attr.db_value = None
                    attr.db_storage_type = JSON_STORAGE_TYPE
                    converted.append(attr)

            if converted and not dry_run:
                with transaction.atomic():
                    # bulk_update deliberately bypasses save()/monitors - the
                    # value is unchanged, only its storage column moves
                    Attribute.objects.bulk_update(converted, VALUE_STORAGE_FIELDS)
            converted_count += len(converted)

            # SharedMemoryModel caches every instantiated row; flush per batch
            # to keep memory flat on large tables
            Attribute.flush_instance_cache()

        prefix = "Would convert" if dry_run else "Converted"
        self.stdout.write(
            f"{prefix} {converted_count} Attribute(s) to json storage, "
            f"kept {kept_pickle_count} as pickle (no JSON representation), "
            f"{failed_count} failed to load, in {batch_count} batch(es)."
        )
