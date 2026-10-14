from django.db import migrations


CHILD_TABLES = (
    (
        'equipment_accountingentry',
        'fk_equipment_accountingentry_equipment_property_number',
    ),
    (
        'equipment_equipmentassignmenthistory',
        'fk_equipment_assignmenthistory_equipment_property_number',
    ),
    (
        'equipment_inventorycustodianslipitem',
        'fk_equipment_icsitem_equipment_property_number',
    ),
    (
        'equipment_propertyacknowledgmentreceiptitem',
        'fk_equipment_paritem_equipment_property_number',
    ),
    (
        'borrowing_borrowrequest',
        'fk_borrowrequest_equipment_property_number',
    ),
    (
        'maintenance_maintenancerequest',
        'fk_maintenancerequest_equipment_property_number',
    ),
)


def _columns(cursor, table_name):
    cursor.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        [table_name],
    )
    return {name: data_type for name, data_type in cursor.fetchall()}


def _equipment_fk_names(cursor, table_name):
    cursor.execute(
        """
        SELECT CONSTRAINT_NAME
        FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = 'equipment_id'
          AND REFERENCED_TABLE_NAME = 'equipment_equipment'
        """,
        [table_name],
    )
    return [name for (name,) in cursor.fetchall()]


def _drop_non_primary_indexes(cursor, table_name, column_name):
    cursor.execute(
        """
        SELECT DISTINCT INDEX_NAME
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
          AND INDEX_NAME <> 'PRIMARY'
        """,
        [table_name, column_name],
    )
    for (index_name,) in cursor.fetchall():
        cursor.execute(f"ALTER TABLE `{table_name}` DROP INDEX `{index_name}`")


def _mysql_remap_equipment_pk(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    cursor = schema_editor.connection.cursor()
    equipment_columns = _columns(cursor, 'equipment_equipment')
    parent_needs_fix = 'id' in equipment_columns or 'equipment_id' in equipment_columns
    child_tables_needing_fix = [
        table_name
        for table_name, _ in CHILD_TABLES
        if _columns(cursor, table_name).get('equipment_id') != 'varchar'
    ]

    if not parent_needs_fix and not child_tables_needing_fix:
        return

    if not parent_needs_fix and child_tables_needing_fix:
        raise RuntimeError(
            'Equipment child tables still use legacy integer keys, '
            'but equipment_equipment is already on property_number.'
        )

    if 'property_number' not in equipment_columns:
        raise RuntimeError('equipment_equipment.property_number is missing.')

    cursor.execute("DROP TEMPORARY TABLE IF EXISTS equipment_pk_map")
    cursor.execute(
        """
        CREATE TEMPORARY TABLE equipment_pk_map AS
        SELECT id AS old_id, property_number
        FROM equipment_equipment
        """
    )
    cursor.execute("ALTER TABLE equipment_pk_map ADD PRIMARY KEY (old_id)")

    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    try:
        for table_name, _ in CHILD_TABLES:
            child_columns = _columns(cursor, table_name)
            if child_columns.get('equipment_id') == 'varchar':
                if '_equipment_pn' in child_columns:
                    cursor.execute(
                        f"ALTER TABLE `{table_name}` DROP COLUMN `_equipment_pn`"
                    )
                for fk_name in _equipment_fk_names(cursor, table_name):
                    cursor.execute(
                        f"ALTER TABLE `{table_name}` DROP FOREIGN KEY `{fk_name}`"
                    )
                continue

            if '_equipment_pn' not in child_columns:
                cursor.execute(
                    f"""
                    ALTER TABLE `{table_name}`
                    ADD COLUMN `_equipment_pn` varchar(50) NULL
                    """
                )

            cursor.execute(
                f"""
                UPDATE `{table_name}` AS child
                INNER JOIN equipment_pk_map AS mapping
                    ON child.equipment_id = mapping.old_id
                SET child._equipment_pn = mapping.property_number
                """
            )

            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM `{table_name}`
                WHERE equipment_id IS NOT NULL AND _equipment_pn IS NULL
                """
            )
            missing = cursor.fetchone()[0]
            if missing:
                raise RuntimeError(
                    f'Unable to map {missing} legacy equipment references in {table_name}.'
                )

            for fk_name in _equipment_fk_names(cursor, table_name):
                cursor.execute(
                    f"ALTER TABLE `{table_name}` DROP FOREIGN KEY `{fk_name}`"
                )

            cursor.execute(
                f"""
                ALTER TABLE `{table_name}`
                MODIFY COLUMN `equipment_id` varchar(50) NOT NULL
                """
            )
            cursor.execute(
                f"""
                UPDATE `{table_name}`
                SET `equipment_id` = `_equipment_pn`
                """
            )
            cursor.execute(f"ALTER TABLE `{table_name}` DROP COLUMN `_equipment_pn`")

        equipment_columns = _columns(cursor, 'equipment_equipment')
        if 'id' in equipment_columns or 'equipment_id' in equipment_columns:
            cursor.execute(
                """
                ALTER TABLE `equipment_equipment`
                DROP PRIMARY KEY,
                DROP COLUMN `id`,
                DROP COLUMN `equipment_id`,
                ADD PRIMARY KEY (`property_number`)
                """
            )
            _drop_non_primary_indexes(cursor, 'equipment_equipment', 'property_number')

        for table_name, constraint_name in CHILD_TABLES:
            fk_names = _equipment_fk_names(cursor, table_name)
            for fk_name in fk_names:
                cursor.execute(
                    f"ALTER TABLE `{table_name}` DROP FOREIGN KEY `{fk_name}`"
                )
            cursor.execute(
                f"""
                ALTER TABLE `{table_name}`
                ADD CONSTRAINT `{constraint_name}`
                FOREIGN KEY (`equipment_id`)
                REFERENCES `equipment_equipment` (`property_number`)
                """
            )
    finally:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('equipment', '0017_backfill_created_by_from_audit'),
    ]

    operations = [
        migrations.RunPython(_mysql_remap_equipment_pk, migrations.RunPython.noop),
    ]
