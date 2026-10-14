# Generated manually for property_number primary key migration.

from django.db import migrations, models


CHILD_TABLES = (
    'equipment_accountingentry',
    'equipment_equipmentassignmenthistory',
    'equipment_inventorycustodianslipitem',
    'equipment_propertyacknowledgmentreceiptitem',
    'borrowing_borrowrequest',
    'maintenance_maintenancerequest',
)


def _table_columns(raw_conn, table):
    cursor = raw_conn.cursor()
    cursor.execute(f'PRAGMA table_info({table})')
    return [row[1] for row in cursor.fetchall()]


def _sqlite_remap_equipment_pk(apps, schema_editor):
    if schema_editor.connection.vendor != 'sqlite':
        return

    raw = schema_editor.connection.connection
    raw.execute('PRAGMA foreign_keys=OFF')

    cursor = raw.cursor()
    cursor.execute('SELECT id, property_number FROM equipment_equipment')
    id_to_property = {row[0]: row[1] for row in cursor.fetchall()}

    for table in CHILD_TABLES:
        columns = _table_columns(raw, table)
        if '_equipment_pn' not in columns:
            raw.execute(f'ALTER TABLE {table} ADD COLUMN _equipment_pn varchar(50)')
        for old_id, property_number in id_to_property.items():
            raw.execute(
                f'UPDATE {table} SET _equipment_pn = ? WHERE equipment_id = ?',
                (property_number, old_id),
            )

    cursor.execute(
        '''
        CREATE TABLE equipment_equipment_new (
            property_number varchar(50) NOT NULL PRIMARY KEY,
            name varchar(200) NOT NULL,
            asset_classification varchar(100) NOT NULL,
            brand varchar(100) NOT NULL,
            model varchar(100) NOT NULL,
            serial_number varchar(100) NOT NULL,
            purchase_date date NULL,
            purchase_cost decimal NOT NULL,
            depreciation_method varchar(20) NOT NULL,
            warranty_until date NULL,
            current_location varchar(200) NOT NULL,
            status varchar(20) NOT NULL,
            expected_lifespan_years integer unsigned NOT NULL CHECK (expected_lifespan_years >= 0),
            condition_score integer NOT NULL,
            utilization_percent decimal NOT NULL,
            maintenance_schedule varchar(100) NOT NULL,
            last_inspection_date date NULL,
            qr_code varchar(100) NULL,
            created_at datetime NOT NULL,
            updated_at datetime NOT NULL,
            assigned_user_id bigint NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED,
            department_id bigint NULL REFERENCES equipment_department (id) DEFERRABLE INITIALLY DEFERRED,
            category_id bigint NOT NULL REFERENCES equipment_category (id) DEFERRABLE INITIALLY DEFERRED,
            acquisition_cost decimal NOT NULL,
            classification varchar(30) NOT NULL,
            coa_account_code varchar(20) NOT NULL,
            criterion_future_benefits bool NOT NULL,
            criterion_measurable_cost bool NOT NULL,
            criterion_not_for_resale bool NOT NULL,
            criterion_useful_life bool NOT NULL,
            estimated_useful_life integer unsigned NOT NULL CHECK (estimated_useful_life >= 0),
            fund varchar(50) NOT NULL,
            property_status_id bigint NULL REFERENCES equipment_propertystatus (id) DEFERRABLE INITIALLY DEFERRED,
            fund_source_id bigint NULL REFERENCES equipment_fundsource (id) DEFERRABLE INITIALLY DEFERRED,
            mode_of_procurement_id bigint NULL REFERENCES equipment_modeofprocurement (id) DEFERRABLE INITIALLY DEFERRED,
            supplier_id bigint NULL REFERENCES equipment_supplier (id) DEFERRABLE INITIALLY DEFERRED,
            purchase_order_no varchar(50) NOT NULL,
            quantity integer unsigned NOT NULL CHECK (quantity >= 0),
            unit varchar(30) NOT NULL,
            description text NOT NULL,
            payment_method varchar(30) NOT NULL
        )
        '''
    )
    cursor.execute(
        '''
        INSERT INTO equipment_equipment_new (
            property_number, name, asset_classification, brand, model, serial_number,
            purchase_date, purchase_cost, depreciation_method, warranty_until,
            current_location, status, expected_lifespan_years, condition_score,
            utilization_percent, maintenance_schedule, last_inspection_date, qr_code,
            created_at, updated_at, assigned_user_id, department_id, category_id,
            acquisition_cost, classification, coa_account_code,
            criterion_future_benefits, criterion_measurable_cost,
            criterion_not_for_resale, criterion_useful_life, estimated_useful_life,
            fund, property_status_id, fund_source_id, mode_of_procurement_id,
            supplier_id, purchase_order_no, quantity, unit, description, payment_method
        )
        SELECT
            property_number, name, asset_classification, brand, model, serial_number,
            purchase_date, purchase_cost, depreciation_method, warranty_until,
            current_location, status, expected_lifespan_years, condition_score,
            utilization_percent, maintenance_schedule, last_inspection_date, qr_code,
            created_at, updated_at, assigned_user_id, department_id, category_id,
            acquisition_cost, classification, coa_account_code,
            criterion_future_benefits, criterion_measurable_cost,
            criterion_not_for_resale, criterion_useful_life, estimated_useful_life,
            fund, property_status_id, fund_source_id, mode_of_procurement_id,
            supplier_id, purchase_order_no, quantity, unit, description, payment_method
        FROM equipment_equipment
        '''
    )
    cursor.execute('DROP TABLE equipment_equipment')
    cursor.execute('ALTER TABLE equipment_equipment_new RENAME TO equipment_equipment')

    child_rebuilds = {
        'equipment_accountingentry': '''
            CREATE TABLE equipment_accountingentry_new (
                id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                entry_type varchar(20) NOT NULL,
                jev_number varchar(30) NOT NULL UNIQUE,
                debit_account varchar(20) NOT NULL,
                credit_account varchar(20) NOT NULL,
                amount decimal NOT NULL,
                fund varchar(50) NOT NULL,
                particulars text NOT NULL,
                reference_type varchar(50) NOT NULL,
                reference_id integer unsigned NULL CHECK (reference_id >= 0),
                created_at datetime NOT NULL,
                created_by_id bigint NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED,
                equipment_id varchar(50) NOT NULL REFERENCES equipment_equipment (property_number) DEFERRABLE INITIALLY DEFERRED
            )
        ''',
        'equipment_equipmentassignmenthistory': '''
            CREATE TABLE equipment_equipmentassignmenthistory_new (
                id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                user_name varchar(200) NOT NULL,
                previous_user_name varchar(200) NOT NULL,
                notes varchar(50) NOT NULL,
                assigned_at datetime NOT NULL,
                changed_by_id bigint NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED,
                equipment_id varchar(50) NOT NULL REFERENCES equipment_equipment (property_number) DEFERRABLE INITIALLY DEFERRED,
                user_id bigint NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED
            )
        ''',
        'equipment_inventorycustodianslipitem': '''
            CREATE TABLE equipment_inventorycustodianslipitem_new (
                id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                quantity integer unsigned NOT NULL CHECK (quantity >= 0),
                unit varchar(30) NOT NULL,
                description varchar(500) NOT NULL,
                amount decimal NOT NULL,
                inventory_item_no varchar(50) NOT NULL,
                estimated_unit_cost decimal NOT NULL,
                total_cost decimal NOT NULL,
                useful_life integer unsigned NOT NULL CHECK (useful_life >= 0),
                equipment_id varchar(50) NOT NULL REFERENCES equipment_equipment (property_number) DEFERRABLE INITIALLY DEFERRED,
                ics_id bigint NOT NULL REFERENCES equipment_inventorycustodianslip (id) DEFERRABLE INITIALLY DEFERRED
            )
        ''',
        'equipment_propertyacknowledgmentreceiptitem': '''
            CREATE TABLE equipment_propertyacknowledgmentreceiptitem_new (
                id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                quantity integer unsigned NOT NULL CHECK (quantity >= 0),
                unit varchar(30) NOT NULL,
                description varchar(500) NOT NULL,
                property_number varchar(50) NOT NULL,
                date_acquired date NULL,
                amount decimal NOT NULL,
                equipment_id varchar(50) NOT NULL REFERENCES equipment_equipment (property_number) DEFERRABLE INITIALLY DEFERRED,
                par_id bigint NOT NULL REFERENCES equipment_propertyacknowledgmentreceipt (id) DEFERRABLE INITIALLY DEFERRED
            )
        ''',
        'borrowing_borrowrequest': '''
            CREATE TABLE borrowing_borrowrequest_new (
                id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                quantity integer unsigned NOT NULL CHECK (quantity >= 0),
                purpose text NOT NULL,
                borrow_date date NOT NULL,
                expected_return date NOT NULL,
                actual_return date NULL,
                approval_status varchar(20) NOT NULL,
                approver_notes text NOT NULL,
                created_at datetime NOT NULL,
                updated_at datetime NOT NULL,
                approver_id bigint NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED,
                department_id bigint NULL REFERENCES equipment_department (id) DEFERRABLE INITIALLY DEFERRED,
                employee_id bigint NOT NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED,
                equipment_id varchar(50) NOT NULL REFERENCES equipment_equipment (property_number) DEFERRABLE INITIALLY DEFERRED
            )
        ''',
        'maintenance_maintenancerequest': '''
            CREATE TABLE maintenance_maintenancerequest_new (
                id integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                issue_description text NOT NULL,
                priority varchar(10) NOT NULL,
                estimated_cost decimal NOT NULL,
                actual_cost decimal NOT NULL,
                date_opened date NOT NULL,
                completion_date date NULL,
                repair_status varchar(20) NOT NULL,
                technician_notes text NOT NULL,
                created_at datetime NOT NULL,
                equipment_id varchar(50) NOT NULL REFERENCES equipment_equipment (property_number) DEFERRABLE INITIALLY DEFERRED,
                reported_by_id bigint NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED,
                technician_id bigint NULL REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED
            )
        ''',
    }

    child_inserts = {
        'equipment_accountingentry': '''
            INSERT INTO equipment_accountingentry_new (
                id, entry_type, jev_number, debit_account, credit_account, amount, fund,
                particulars, reference_type, reference_id, created_at, created_by_id, equipment_id
            )
            SELECT
                id, entry_type, jev_number, debit_account, credit_account, amount, fund,
                particulars, reference_type, reference_id, created_at, created_by_id, _equipment_pn
            FROM equipment_accountingentry
        ''',
        'equipment_equipmentassignmenthistory': '''
            INSERT INTO equipment_equipmentassignmenthistory_new (
                id, user_name, previous_user_name, notes, assigned_at,
                changed_by_id, equipment_id, user_id
            )
            SELECT
                id, user_name, previous_user_name, notes, assigned_at,
                changed_by_id, _equipment_pn, user_id
            FROM equipment_equipmentassignmenthistory
        ''',
        'equipment_inventorycustodianslipitem': '''
            INSERT INTO equipment_inventorycustodianslipitem_new (
                id, quantity, unit, description, amount, inventory_item_no,
                estimated_unit_cost, total_cost, useful_life, equipment_id, ics_id
            )
            SELECT
                id, quantity, unit, description, amount, inventory_item_no,
                estimated_unit_cost, total_cost, useful_life, _equipment_pn, ics_id
            FROM equipment_inventorycustodianslipitem
        ''',
        'equipment_propertyacknowledgmentreceiptitem': '''
            INSERT INTO equipment_propertyacknowledgmentreceiptitem_new (
                id, quantity, unit, description, property_number, date_acquired,
                amount, equipment_id, par_id
            )
            SELECT
                id, quantity, unit, description, property_number, date_acquired,
                amount, _equipment_pn, par_id
            FROM equipment_propertyacknowledgmentreceiptitem
        ''',
        'borrowing_borrowrequest': '''
            INSERT INTO borrowing_borrowrequest_new (
                id, quantity, purpose, borrow_date, expected_return, actual_return,
                approval_status, approver_notes, created_at, updated_at,
                approver_id, department_id, employee_id, equipment_id
            )
            SELECT
                id, quantity, purpose, borrow_date, expected_return, actual_return,
                approval_status, approver_notes, created_at, updated_at,
                approver_id, department_id, employee_id, _equipment_pn
            FROM borrowing_borrowrequest
        ''',
        'maintenance_maintenancerequest': '''
            INSERT INTO maintenance_maintenancerequest_new (
                id, issue_description, priority, estimated_cost, actual_cost,
                date_opened, completion_date, repair_status, technician_notes,
                created_at, equipment_id, reported_by_id, technician_id
            )
            SELECT
                id, issue_description, priority, estimated_cost, actual_cost,
                date_opened, completion_date, repair_status, technician_notes,
                created_at, _equipment_pn, reported_by_id, technician_id
            FROM maintenance_maintenancerequest
        ''',
    }

    for table in CHILD_TABLES:
        cursor.execute(child_rebuilds[table])
        cursor.execute(child_inserts[table])
        cursor.execute(f'DROP TABLE {table}')
        cursor.execute(f'ALTER TABLE {table}_new RENAME TO {table}')

    cursor.execute('PRAGMA foreign_keys=ON')


def _noop_reverse(apps, schema_editor):
    raise RuntimeError('Cannot reverse equipment property_number primary key migration.')


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('equipment', '0014_equipment_description_payment_method'),
        ('borrowing', '0001_initial'),
        ('maintenance', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(_sqlite_remap_equipment_pk, _noop_reverse),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterModelOptions(
                    name='equipment',
                    options={'ordering': ['property_number']},
                ),
                migrations.RemoveField(
                    model_name='equipment',
                    name='equipment_id',
                ),
                migrations.RemoveField(
                    model_name='equipment',
                    name='id',
                ),
                migrations.AlterField(
                    model_name='equipment',
                    name='property_number',
                    field=models.CharField(max_length=50, primary_key=True, serialize=False),
                ),
            ],
        ),
    ]
