import base64
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ElearningExportImport(models.TransientModel):
    _name = 'elearning.export.import'
    _description = 'eLearning Course Export/Import Wizard'

    course_ids = fields.Many2many('slide.course', string='Courses')
    data_file = fields.Binary(string='Import File')
    filename = fields.Char(string='Filename')
    export_format = fields.Selection([
        ('json', 'JSON'),
        ('xml', 'XML')
    ], string='Export Format', default='json')

    def action_export(self):
        _logger.info("Starting eLearning course export for %s courses", len(self.course_ids))
        # Export logic: serialize course data to selected format
        data = self._prepare_export_data()
        file_data = self._serialize_data(data, self.export_format)
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/export/{self._context.get("export_id")}',
            'target': 'self',
        }

    def action_import(self):
        _logger.info("Starting eLearning course import from file %s", self.filename)
        if not self.data_file:
            raise UserError("Please select a file to import.")
        # Import logic: parse file and create/update courses
        data = self._parse_import_file()
        self._create_courses(data)
        return {'type': 'ir.actions.act_window_close'}
