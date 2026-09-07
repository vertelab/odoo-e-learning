{
    'name': 'eLearning Export Import',
'author': 'Vertel Sverige AB',
    'version': '18.0.1.0.0',
    'category': 'eLearning',
    'summary': 'Export and import eLearning courses easily',
    'depends': ['website_slides'],
    'data': [
        'security/ir.model.access.csv',
        'views/elearning_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'license': 'AGPL-3',
}
