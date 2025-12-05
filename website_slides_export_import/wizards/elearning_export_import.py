import base64
import logging
import io
from lxml import etree
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class ElearningExportImport(models.TransientModel):
    _name = 'elearning.export.import'
    _description = 'eLearning Course Export/Import Wizard'

    course_ids = fields.Many2many('slide.channel', string='Courses')
    data_file = fields.Binary(string='Import File')
    filename = fields.Char(string='Filename')
    export_format = fields.Selection([
        ('xml', 'XML')
    ], string='Export Format', default='xml')

    def action_export(self):
        _logger.info("Starting eLearning course export for %s courses", len(self.course_ids))
        if not self.course_ids:
            raise UserError("Please select at least one course to export.")
        
        data = self._prepare_export_data()
        xml_content = self._generate_xml(data)
        
        # Create attachment and return download action
        attachment = self.env['ir.attachment'].create({
            'name': f'elearning_courses_{len(self.course_ids)}_courses.xml',
            'type': 'binary',
            'datas': base64.b64encode(xml_content.encode('utf-8')),
            'mimetype': 'application/xml',
            'res_model': self._name,
            'res_id': self.id,
        })
        
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }



    def action_import(self):
        if not self.data_file:
            raise UserError("Please select a file to import.")
        
        try:
            xml_content = base64.b64decode(self.data_file).decode('utf-8')
            root = etree.fromstring(xml_content.encode('utf-8'))
            
            imported_count = 0
            for course_elem in root.findall('course'):
                course_name = course_elem.find('name').text
                course_description = course_elem.find('description').text or ''
                _logger.warning(f"{course_description=}")
                new_course = self.env['slide.channel'].create({
                    'name': course_name,
                    'description': course_description,
                })
                
                imported_count += 1
                _logger.info("Imported course: %s (ID: %s)", course_name, new_course.id)
            
            _logger.info("Import completed successfully: %s courses created", imported_count)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Import Successful',
                    'message': f'{imported_count} courses imported successfully!',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error("Import failed: %s", str(e))
            raise UserError(f"Import failed: {str(e)}")
      

    def _prepare_export_data(self):
        export_data = {
            'courses': [],
            'export_date': fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        for course in self.course_ids:
            course_data = {
                'id': course.id,
                'name': course.name,
                'description': course.description or ''
            }
            export_data['courses'].append(course_data)
        
        return export_data

    def _generate_xml(self, data):
        xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml_lines.append('<elearning_export version="1.0">')
        xml_lines.append(f'  <export_date>{data["export_date"]}</export_date>')
        xml_lines.append(f'  <total_courses>{len(data["courses"])}</total_courses>')
        
        for course_data in data['courses']:
            xml_lines.append(f'  <course id="{course_data["id"]}">')
            xml_lines.append(f'    <name>{course_data["name"]}</name>')
            xml_lines.append(f'    <description>{course_data["description"]}</description>')
            xml_lines.append('  </course>')
        
        xml_lines.append('</elearning_export>')
        xml_string = '\n'.join(xml_lines)
        
        _logger.info("Manual XML generated successfully")
        return xml_string


            
            
        
