"""
Management command to seed the database with realistic sample data.
Run: python manage.py seed_data
"""
import random
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from accounts.models import Role
from equipment.models import Department, Equipment, Category, ChartOfAccount, FundSource, Supplier
from borrowing.models import BorrowRequest
from maintenance.models import MaintenanceRequest
from equipment.coa import update_coa_fields

User = get_user_model()

SEED_CATEGORY_CODES = {
    'ICT Equipment': '05-03',
    'Office Equipment': '05-02',
    'Multimedia': '05-07',
    'Furniture': '06-01',
    'Machinery': '05-01',
    'Vehicle': '05-99',
    'Other': '05-99',
}


def get_seed_category(name):
    code = SEED_CATEGORY_CODES.get(name, '05-99')
    category = Category.objects.filter(code=code).first()
    if category:
        return category
    return Category.objects.create(
        code=code, name=name, status=Category.STATUS_ACTIVE,
    )


def get_seed_fund_source(name):
    fund = FundSource.objects.filter(name=name).first()
    if fund:
        return fund
    code = name[:20].upper().replace(' ', '-')
    while FundSource.objects.filter(code=code).exists():
        code = f'{code[:15]}-{FundSource.objects.count()}'
    return FundSource.objects.create(
        code=code, name=name, status=FundSource.STATUS_ACTIVE,
    )


def get_seed_supplier(name):
    supplier = Supplier.objects.filter(name=name).first()
    if supplier:
        return supplier
    return Supplier.objects.create(name=name, status=Supplier.STATUS_ACTIVE)


class Command(BaseCommand):
    help = 'Seed the database with sample data for the PMS.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING('Seeding database...'))

        # ── 1. Offices / Departments ─────────────────────────────────────
        dept_data = [
            ('Administration', 'ADMIN'),
            ('IT Department', 'IT'),
            ('Engineering', 'ENG'),
            ('Accounting', 'ACCTG'),
            ('Operations', 'OPS'),
        ]
        depts = {}
        for name, code in dept_data:
            dept, created = Department.objects.get_or_create(
                code=code,
                defaults={'name': name, 'status': Department.STATUS_ACTIVE},
            )
            if not created and dept.status != Department.STATUS_ACTIVE:
                dept.status = Department.STATUS_ACTIVE
                dept.save(update_fields=['status'])
            depts[code] = dept
        self.stdout.write(f'  ✔ {len(depts)} offices / departments')

        # ── 1b. Roles ────────────────────────────────────────────────────
        role_names = ['Admin', 'Property Custodian', 'Supply Officer', 'Technician', 'Employee']
        roles = {}
        for name in role_names:
            role, created = Role.objects.get_or_create(
                name=name,
                defaults={'status': Role.STATUS_ACTIVE},
            )
            role.apply_named_default(fallback='staff')
            if not created and role.status != Role.STATUS_ACTIVE:
                role.status = Role.STATUS_ACTIVE
            role.save()
            roles[name] = role
        self.stdout.write(f'  ✔ {len(roles)} roles')

        # ── 2. Users ───────────────────────────────────────────────────
        users_data = [
            ('admin', 'admin123', 'Admin', True, 'Admin', 'User', 'ADMIN'),
            ('custodian1', 'pass1234', 'Property Custodian', False, 'Maria', 'Santos', 'ADMIN'),
            ('tech1', 'pass1234', 'Technician', False, 'Juan', 'Dela Cruz', 'IT'),
            ('employee1', 'pass1234', 'Employee', False, 'Ana', 'Reyes', 'OPS'),
            ('employee2', 'pass1234', 'Employee', False, 'Pedro', 'Garcia', 'ACCTG'),
            ('employee3', 'pass1234', 'Employee', False, 'Rosa', 'Lim', 'ENG'),
        ]
        created_users = {}
        for username, password, role, is_super, first, last, dept_code in users_data:
            if not User.objects.filter(username=username).exists():
                u = User.objects.create_superuser(username=username, password=password,
                                                   email=f'{username}@pms.ph') if is_super else \
                    User.objects.create_user(username=username, password=password,
                                             email=f'{username}@pms.ph')
                u.role = roles.get(role)
                u.first_name = first
                u.last_name = last
                u.department = depts.get(dept_code)
                u.save()
            created_users[username] = User.objects.get(username=username)
        self.stdout.write(f'  ✔ {len(created_users)} users')

        # ── 2b. Chart of Accounts (Annex B) ────────────────────────────
        coa_seed = [
            # Semi-expendable asset accounts (10405010–10405990)
            ('10405010', 'Semi-Expendable — ICT Equipment', 'asset', ['ICT Equipment']),
            ('10405020', 'Semi-Expendable — Office Equipment', 'asset', ['Office Equipment']),
            ('10405030', 'Semi-Expendable — Furniture & Fixtures', 'asset', ['Furniture']),
            ('10405040', 'Semi-Expendable — Multimedia Equipment', 'asset', ['Multimedia']),
            ('10405050', 'Semi-Expendable — Machinery & Equipment', 'asset', ['Machinery']),
            ('10405990', 'Semi-Expendable — Other Property', 'asset', ['Other', 'Vehicle']),
            ('10406010', 'Semi-Expendable Property — LGU', 'asset', []),
            ('10406020', 'Semi-Expendable Property — National', 'asset', []),
            # Expense on issuance (50203210/220, 50213210/220)
            ('50203210', 'Supplies and Materials Expenses — Issuance', 'expense_issuance', ['Office Equipment', 'Furniture']),
            ('50203220', 'Semi-Expendable Property Issued — LGU', 'expense_issuance', ['ICT Equipment', 'Multimedia']),
            ('50213210', 'Cost of Services — Semi-Expendable Issuance', 'expense_issuance', ['Machinery']),
            ('50213220', 'Semi-Expendable Issued — National', 'expense_issuance', ['Other']),
        ]
        for code, desc, acct_type, cat_names in coa_seed:
            coa, _ = ChartOfAccount.objects.get_or_create(
                code=code,
                defaults={'description': desc, 'account_type': acct_type},
            )
            for cat_name in cat_names:
                cat = get_seed_category(cat_name)
                coa.categories.add(cat)
        self.stdout.write(f'  ✔ {ChartOfAccount.objects.count()} chart of account codes')

        # ── 3. Equipment ───────────────────────────────────────────────
        suppliers = ['TechSource PH', 'Office Depot Manila', 'Samsung Philippines',
                     'HP Philippines', 'Acer PH', 'Panasonic Corp', 'Canon PH']
        locations = ['Admin Office', 'IT Room', 'Engineering Lab', 'Accounting Office',
                     'Operations Center', 'Conference Room A', 'Server Room']
        schedules = ['Every 6 months', 'Annually', 'Quarterly', 'Every 3 months']

        equipment_templates = [
            # (name, category, brand, model, cost, lifespan)
            ('Desktop Computer', 'ICT Equipment', 'Dell', 'OptiPlex 7090', 45000, 5),
            ('Laptop Computer', 'ICT Equipment', 'HP', 'EliteBook 840', 65000, 4),
            ('Laptop Computer', 'ICT Equipment', 'Lenovo', 'ThinkPad E14', 55000, 4),
            ('Printer', 'ICT Equipment', 'Canon', 'PIXMA G4010', 8500, 5),
            ('Printer (Laser)', 'ICT Equipment', 'HP', 'LaserJet Pro M404n', 18000, 6),
            ('Network Switch', 'ICT Equipment', 'Cisco', 'SG110-16', 12000, 7),
            ('UPS', 'ICT Equipment', 'APC', 'Back-UPS 650VA', 4500, 5),
            ('Monitor', 'ICT Equipment', 'Samsung', 'F24T450', 9800, 6),
            ('Projector', 'Multimedia', 'Epson', 'EB-X41', 28000, 6),
            ('Projector', 'Multimedia', 'Panasonic', 'PT-VX615N', 45000, 7),
            ('Video Camera', 'Multimedia', 'Sony', 'HXR-NX5R', 120000, 8),
            ('Scanner', 'ICT Equipment', 'Epson', 'DS-530', 15000, 5),
            ('External Hard Drive', 'ICT Equipment', 'Seagate', 'Backup Plus 4TB', 3800, 4),
            ('Office Chair', 'Furniture', 'HM', 'Executive Mesh', 6500, 10),
            ('Conference Table', 'Furniture', 'IKEA', 'BEKANT', 25000, 15),
            ('Air Conditioner', 'Office Equipment', 'Carrier', 'Optimax 2HP', 35000, 10),
            ('Air Conditioner', 'Office Equipment', 'Daikin', 'Inverter 2.5HP', 42000, 10),
            ('Photocopier', 'Office Equipment', 'Ricoh', 'IM 2702', 95000, 8),
            ('Fax Machine', 'Office Equipment', 'Brother', 'FAX-2840', 4200, 7),
            ('Shredder', 'Office Equipment', 'Fellowes', 'Powershred 99Ci', 15500, 7),
            ('Generator', 'Machinery', 'Honda', 'EU7000is', 185000, 15),
            ('Water Dispenser', 'Office Equipment', 'Bluewater', 'Pro 14', 22000, 8),
            ('CCTV System', 'ICT Equipment', 'Hikvision', 'DS-2CD2143', 35000, 7),
            ('Whiteboard', 'Office Equipment', 'Quartet', 'Classic 8x4', 4800, 10),
            ('Telephone System', 'Office Equipment', 'Panasonic', 'KX-TEB308', 18000, 8),
            ('Microwave Oven', 'Office Equipment', 'Sharp', 'R-359T', 5500, 8),
            ('Refrigerator', 'Office Equipment', 'Samsung', 'RT22FARADSA', 18500, 10),
            ('Laminator', 'Office Equipment', 'GBC', 'Fusion 1000L', 4200, 6),
            ('Binding Machine', 'Office Equipment', 'Fellowes', 'Galaxy 500', 8000, 8),
            ('Label Printer', 'ICT Equipment', 'Dymo', 'LabelWriter 450', 6500, 5),
            ('Server Rack', 'ICT Equipment', 'APC', 'NetShelter SX 12U', 28000, 10),
            ('IP Phone', 'ICT Equipment', 'Cisco', 'CP-8845', 9500, 7),
            ('Drawing Board', 'Machinery', 'Alvin', 'ProDraft DB2024', 7500, 10),
            ('Oscilloscope', 'Machinery', 'Rigol', 'DS1054Z', 18000, 8),
            ('Power Drill', 'Machinery', 'Bosch', 'GSR 18V-60', 12500, 7),
            ('Filing Cabinet', 'Furniture', 'Steel Office', '4-Drawer', 9800, 15),
            ('Standing Fan', 'Office Equipment', 'Hanabishi', 'HEF-20U', 1800, 5),
            ('Vacuum Cleaner', 'Office Equipment', 'Dyson', 'V11 Outsize', 25000, 6),
            ('Tablet', 'ICT Equipment', 'Apple', 'iPad Pro 11"', 48000, 4),
            ('Walkie Talkie Set', 'ICT Equipment', 'Motorola', 'T80', 8500, 5),
            # COA threshold samples — Low-Value (≤₱5k), Semi-Expendable, PPE (≥₱50k)
            ('USB Flash Drive 64GB', 'ICT Equipment', 'SanDisk', 'Ultra 64GB', 3500, 3),
            ('Office Desk', 'Furniture', 'Steel Office', 'Executive', 25000, 10),
            ('Server Rack Cabinet', 'ICT Equipment', 'APC', 'NetShelter SX 42U', 75000, 12),
        ]

        statuses = ['Available'] * 20 + ['Borrowed'] * 8 + ['Maintenance'] * 7 + ['Retired'] * 5
        dept_list = list(depts.values())
        eq_users = [created_users['employee1'], created_users['employee2'],
                    created_users['employee3'], None, None]

        created_equipment = []
        for i, (name, category_name, brand, model, cost, lifespan) in enumerate(equipment_templates):
            prop_num = f'PROP-{i+1:04d}'
            if Equipment.objects.filter(property_number=prop_num).exists():
                created_equipment.append(Equipment.objects.get(property_number=prop_num))
                continue

            category = get_seed_category(category_name)

            purchase_date = date.today() - timedelta(days=random.randint(180, 2000))
            status = statuses[i % len(statuses)]
            condition = random.randint(55, 100) if status != 'Retired' else random.randint(10, 45)
            utilization = Decimal(str(random.randint(20, 90)))

            fund_name = random.choice(['General Fund', 'Special Education Fund', 'Trust Fund'])
            fund_source = get_seed_fund_source(fund_name)
            eq = Equipment.objects.create(
                property_number=prop_num,
                name=name,
                category=category,
                brand=brand,
                model=model,
                serial_number=f'SN{random.randint(100000, 999999)}',
                purchase_date=purchase_date,
                purchase_cost=Decimal(str(cost)),
                acquisition_cost=Decimal(str(cost)),
                fund=fund_name,
                fund_source=fund_source,
                estimated_useful_life=lifespan,
                depreciation_method=random.choice(['straight_line', 'declining_balance']),
                warranty_until=purchase_date + timedelta(days=random.randint(365, 1095)),
                supplier=get_seed_supplier(random.choice(suppliers)),
                department=dept_list[i % len(dept_list)],
                current_location=random.choice(locations),
                assigned_user=random.choice(eq_users),
                status=status,
                expected_lifespan_years=lifespan,
                condition_score=condition,
                utilization_percent=utilization,
                maintenance_schedule=random.choice(schedules),
                last_inspection_date=date.today() - timedelta(days=random.randint(30, 180)),
            )
            update_coa_fields(eq)
            Equipment.objects.filter(pk=eq.pk).update(
                classification=eq.classification,
                coa_account_code=eq.coa_account_code,
            )
            created_equipment.append(eq)

        self.stdout.write(f'  ✔ {len(created_equipment)} equipment records')

        # ── 4. Borrow Requests ─────────────────────────────────────────
        employees = [created_users['employee1'], created_users['employee2'], created_users['employee3']]
        approver = created_users['custodian1']
        available_eq = [e for e in created_equipment if e.status in ('Available', 'Borrowed')]

        borrow_statuses = ['Pending', 'Approved', 'Returned', 'Returned', 'Overdue', 'Rejected']
        for i in range(15):
            eq = available_eq[i % len(available_eq)]
            emp = employees[i % len(employees)]
            borrow_date = date.today() - timedelta(days=random.randint(5, 60))
            expected_return = borrow_date + timedelta(days=random.randint(3, 14))
            b_status = borrow_statuses[i % len(borrow_statuses)]
            actual_return = None
            if b_status == 'Returned':
                actual_return = expected_return - timedelta(days=random.randint(0, 2))

            if not BorrowRequest.objects.filter(employee=emp, equipment=eq, borrow_date=borrow_date).exists():
                BorrowRequest.objects.create(
                    employee=emp,
                    department=emp.department,
                    equipment=eq,
                    quantity=1,
                    purpose=random.choice(['For project use', 'Training session', 'Field work',
                                           'Client presentation', 'Office use']),
                    borrow_date=borrow_date,
                    expected_return=expected_return,
                    actual_return=actual_return,
                    approval_status=b_status,
                    approver=approver if b_status != 'Pending' else None,
                    approver_notes='' if b_status == 'Pending' else 'Approved.',
                )

        borrow_count = BorrowRequest.objects.count()
        self.stdout.write(f'  ✔ {borrow_count} borrow requests')

        # ── 5. Maintenance Requests ────────────────────────────────────
        technician = created_users['tech1']
        reporter = created_users['employee1']
        maint_eq = [e for e in created_equipment
                    if e.status in ('Maintenance', 'Available')][:15]

        issues = [
            'Screen flickering and occasional blackouts',
            'Fan making unusual noise',
            'Battery not charging',
            'Keyboard keys not responding',
            'Network connectivity issues',
            'Print quality degradation',
            'Paper jam issues',
            'Overheating during extended use',
            'Software crash on startup',
            'Power button not working',
        ]
        priorities = ['Low', 'Medium', 'High', 'Critical']
        maint_statuses = ['Open', 'In Progress', 'Completed', 'Completed', 'Completed', 'Open']

        for i, eq in enumerate(maint_eq[:12]):
            m_status = maint_statuses[i % len(maint_statuses)]
            est_cost = Decimal(str(random.randint(500, 8000)))
            actual_cost = est_cost * Decimal(str(random.uniform(0.8, 1.3))) if m_status == 'Completed' else Decimal('0')
            completion = date.today() - timedelta(days=random.randint(1, 30)) if m_status == 'Completed' else None

            if not MaintenanceRequest.objects.filter(equipment=eq).exists():
                MaintenanceRequest.objects.create(
                    equipment=eq,
                    reported_by=reporter,
                    issue_description=issues[i % len(issues)],
                    priority=priorities[i % len(priorities)],
                    technician=technician,
                    estimated_cost=est_cost,
                    actual_cost=actual_cost.quantize(Decimal('0.01')),
                    repair_status=m_status,
                    completion_date=completion,
                    technician_notes='Diagnosis complete.' if m_status != 'Open' else '',
                )

        maint_count = MaintenanceRequest.objects.count()
        self.stdout.write(f'  ✔ {maint_count} maintenance requests')

        # ── 6. Sample PPE with PAR (Annex A.1 demo) ────────────────────
        from equipment.models import PropertyAcknowledgmentReceipt
        from equipment.par import create_par_for_issuance, get_active_par_for_equipment

        custodian = created_users['custodian1']
        employee = created_users['employee1']
        demo_prop = 'PROP-PAR-DEMO'

        if not Equipment.objects.filter(property_number=demo_prop).exists():
            ict_cat = get_seed_category('ICT Equipment')
            general_fund = get_seed_fund_source('General Fund')
            demo_ppe = Equipment(
                property_number=demo_prop,
                name='Enterprise Server',
                category=ict_cat,
                brand='Dell',
                model='PowerEdge R750',
                serial_number='SN-PAR-DEMO-001',
                purchase_date=date.today() - timedelta(days=120),
                purchase_cost=Decimal('85000'),
                acquisition_cost=Decimal('85000'),
                fund='General Fund',
                fund_source=general_fund,
                estimated_useful_life=8,
                criterion_future_benefits=True,
                criterion_measurable_cost=True,
                criterion_useful_life=True,
                criterion_not_for_resale=True,
                department=depts['IT'],
                current_location='Server Room',
                assigned_user=employee,
                status='Borrowed',
                supplier=get_seed_supplier('Dell Philippines'),
            )
            demo_ppe._assignment_changed_by = custodian
            demo_ppe.save()
            self.stdout.write(f'  ✔ Demo PPE {demo_prop} with PAR issuance')
        else:
            demo_ppe = Equipment.objects.get(property_number=demo_prop)
            if not get_active_par_for_equipment(demo_ppe):
                demo_ppe.assigned_user = employee
                demo_ppe._assignment_changed_by = custodian
                demo_ppe.save()
                if not get_active_par_for_equipment(demo_ppe):
                    history = demo_ppe.assignment_history.order_by('-assigned_at').first()
                    create_par_for_issuance(
                        demo_ppe,
                        end_user=employee,
                        custodian=custodian,
                        reference_type='EquipmentAssignmentHistory',
                        reference_id=history.pk if history else None,
                        issue_date=date.today(),
                    )
            self.stdout.write(f'  ✔ Demo PPE {demo_prop} PAR verified')

        par_count = PropertyAcknowledgmentReceipt.objects.count()
        self.stdout.write(f'  ✔ {par_count} Property Acknowledgment Receipt(s)')

        # ── 7. COA Forms & SPC demo data ─────────────────────────────
        from equipment.coa import get_issuance_events, get_spc_transactions, process_issuance

        custodian = created_users['custodian1']
        employee1 = created_users['employee1']
        employee3 = created_users['employee3']
        demo_today = date.today()

        def _demo_borrow(emp, eq, borrow_date, expected_return, status,
                         actual_return=None, purpose_tag=''):
            """Idempotent approved/returned borrow with ICS/PAR issuance."""
            purpose = f'[COA-DEMO]{purpose_tag}'
            br = BorrowRequest.objects.filter(equipment=eq, purpose=purpose).first()
            if br:
                return br
            br = BorrowRequest.objects.create(
                employee=emp,
                department=emp.department,
                equipment=eq,
                quantity=1,
                purpose=purpose,
                borrow_date=borrow_date,
                expected_return=expected_return,
                actual_return=actual_return,
                approval_status=status,
                approver=custodian if status in ('Approved', 'Returned', 'Overdue') else None,
                approver_notes='COA demo issuance.',
            )
            if status in ('Approved', 'Returned', 'Overdue'):
                eq.status = 'Borrowed' if status == 'Approved' else 'Available'
                eq.save(update_fields=['status'])
                process_issuance(
                    eq,
                    end_user=emp,
                    custodian=custodian,
                    reference_type='BorrowRequest',
                    reference_id=br.pk,
                    created_by=custodian,
                )
            return br

        # Desktop Computer — ICS issuance rows (matches COA Forms table demo)
        desktop = Equipment.objects.filter(property_number='PROP-0001').first()
        if desktop:
            _demo_borrow(
                employee1, desktop, demo_today, demo_today + timedelta(days=7),
                'Approved', purpose_tag=' Desktop Computer — Ana Reyes',
            )
            if desktop.assigned_user_id != employee3.pk:
                desktop.assigned_user = employee3
                desktop.status = 'Borrowed'
                desktop._assignment_changed_by = custodian
                desktop.save()

        # Semi-expendable SPC demo — full ledger history for Annex A.2
        demo_spc_prop = 'PROP-SPC-DEMO'
        if not Equipment.objects.filter(property_number=demo_spc_prop).exists():
            multi_cat = get_seed_category('Multimedia')
            general_fund = get_seed_fund_source('General Fund')
            demo_spc = Equipment(
                property_number=demo_spc_prop,
                name='Conference Projector',
                category=multi_cat,
                brand='Epson',
                model='EB-X41',
                serial_number='SN-SPC-DEMO-2025-0042',
                purchase_date=date(2025, 1, 15),
                purchase_cost=Decimal('28000'),
                acquisition_cost=Decimal('28000'),
                fund='General Fund',
                fund_source=general_fund,
                estimated_useful_life=6,
                department=depts['OPS'],
                current_location='Conference Room A',
                status='Available',
                supplier=get_seed_supplier('Epson Philippines'),
            )
            demo_spc.save()
            self.stdout.write(f'  ✔ Demo semi-expendable {demo_spc_prop} created')
        else:
            demo_spc = Equipment.objects.get(property_number=demo_spc_prop)

        _demo_borrow(
            employee1, demo_spc, date(2025, 6, 1), date(2025, 6, 7),
            'Returned', actual_return=date(2025, 6, 10),
            purpose_tag=' SPC — Ana Reyes borrow/return',
        )
        _demo_borrow(
            employee3, demo_spc, date(2025, 8, 1), date(2025, 8, 14),
            'Approved', purpose_tag=' SPC — Rosa Lim active borrow',
        )

        if not MaintenanceRequest.objects.filter(
            equipment=demo_spc, issue_description__startswith='[COA-DEMO]'
        ).exists():
            MaintenanceRequest.objects.create(
                equipment=demo_spc,
                reported_by=employee1,
                issue_description='[COA-DEMO] Lamp dimming — preventive replacement',
                priority='Medium',
                technician=created_users['tech1'],
                estimated_cost=Decimal('3500'),
                actual_cost=Decimal('3200'),
                repair_status='Completed',
                completion_date=date(2025, 9, 15),
                technician_notes='Lamp module replaced.',
            )

        issuance_count = len(get_issuance_events())
        spc_rows = len(get_spc_transactions(demo_spc))
        self.stdout.write(
            f'  ✔ COA demo data — {issuance_count} issuance event(s), '
            f'{spc_rows} SPC ledger row(s) for {demo_spc_prop}'
        )

        # ── Site settings — PAR supply officer defaults ─────────────────
        from core.models import SiteSettings
        site = SiteSettings.get_solo()
        officer = created_users.get('custodian1')
        site_updates = []
        if officer and not (site.par_received_from_name or '').strip():
            site.par_received_from_name = officer.get_full_name() or officer.username
            site_updates.append('par_received_from_name')
        if not (site.par_received_from_position or '').strip():
            site.par_received_from_position = 'Supply Officer'
            site_updates.append('par_received_from_position')
        if site_updates:
            site.save(update_fields=site_updates)
            self.stdout.write('  ✔ Site settings — PAR supply officer signatories')

        self.stdout.write(self.style.SUCCESS('\n✅ Database seeded successfully!'))
        self.stdout.write(self.style.SUCCESS('   Login: admin / admin123'))
