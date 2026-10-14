"""URL patterns for reports app."""
from django.urls import path
from . import views, coa_views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_index, name='index'),
    path('export/csv/', views.export_csv, name='export_csv'),
    path('export/excel/', views.export_excel, name='export_excel'),
    path('export/inventory-pdf/', views.export_inventory_pdf, name='export_inventory_pdf'),
    path('export/pdf/', views.export_pdf, name='export_pdf'),
    path('export/par/', views.export_par, name='export_par'),
    path('export/par/excel/', views.export_par_excel, name='export_par_excel'),
    # COA Forms & Ledgers
    path('coa/', coa_views.coa_forms_index, name='coa_forms'),
    path('coa/par-register/', coa_views.par_register, name='par_register'),
    path('coa/par-register/all/', coa_views.par_print_all, name='par_print_all'),
    path('coa/par-register/all/excel/', coa_views.par_export_all_excel, name='par_export_all_excel'),
    path('coa/ics-register/', coa_views.ics_register, name='ics_register'),
    path('coa/ics-register/all/', coa_views.ics_print_all, name='ics_print_all'),
    path('coa/ics-register/all/excel/', coa_views.ics_export_all_excel, name='ics_export_all_excel'),
    path('coa/spc-register/', coa_views.spc_register, name='spc_register'),
    path('coa/spc-register/all/', coa_views.spc_print_all, name='spc_print_all'),
    path('coa/spc-register/all/excel/', coa_views.spc_export_all_excel, name='spc_export_all_excel'),
    path('coa/splc-register/', coa_views.splc_register, name='splc_register'),
    path('coa/splc-register/all/', coa_views.splc_print_all, name='splc_print_all'),
    path('coa/splc-register/all/excel/', coa_views.splc_export_all_excel, name='splc_export_all_excel'),
    path('coa/par/<int:pk>/', coa_views.par_print, name='par_print'),
    path('coa/par/assigned/', coa_views.par_print_assigned, name='par_print_assigned'),
    path('coa/par/equipment/<str:equipment_id>/', coa_views.par_print_equipment, name='par_print_equipment'),
    path('coa/ics/<int:pk>/', coa_views.ics_print, name='ics_print'),
    path('coa/ics/equipment/<str:equipment_id>/', coa_views.ics_print_equipment, name='ics_print_equipment'),
    path('coa/par/<str:reference_type>/<str:reference_id>/', coa_views.coa_print_par, name='coa_par'),
    path('coa/ics/<str:reference_type>/<str:reference_id>/', coa_views.coa_print_ics, name='coa_ics'),
    path('coa/spc/all/', coa_views.coa_print_all_spc, name='coa_spc_all'),
    path('coa/spc/<str:equipment_id>/', coa_views.coa_print_spc, name='coa_spc'),
    path('coa/spc/<str:equipment_id>/excel/', coa_views.coa_export_spc_excel, name='coa_spc_excel'),
    path('coa/splc/all/', coa_views.coa_print_all_splc, name='coa_splc_all'),
    path('coa/splc/<str:equipment_id>/', coa_views.coa_print_splc, name='coa_splc'),
    path('coa/splc/<str:equipment_id>/excel/', coa_views.coa_export_splc_excel, name='coa_splc_excel'),
    path('coa/rpcsp/', coa_views.coa_print_rpcsp, name='coa_rpcsp'),
]
