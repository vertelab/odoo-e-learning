import base64
import logging
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
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

        xml_content = self._generate_xml()

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

    def _get_whitelist_config(self):
        return {
            'name': True,
            'description': True,
            'channel_type': True,
            'image_1920': True,

            # Many2many - will create if missing
            # 'tag_ids': ['name'], # Many2many

            # One2many - export with nested fields
            'slide_ids': [
                'name',
                'is_category',
                'slide_category',
                'sequence',
                'slide_type',
                'image_1920',
                'url',
                'html_content',
                'description',
                {
                    'question_ids': [
                        'question',
                        'sequence',
                        {
                            'answer_ids': ['text_value', 'is_correct', 'comment']
                        }

                    ]
                },
            ],
        }

    def _get_field_config(self, field_name, config=None):
        if config is None:
            config = self._get_whitelist_config()

        if field_name in config:
            return config[field_name]

        return None

    def _generate_xml(self):
        root = ET.Element('elearning_export', version="1.0")

        # Add metadata
        ET.SubElement(root, 'export_date').text = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ET.SubElement(root, 'total_courses').text = str(len(self.course_ids))

        # Get model info
        ir_model_id = self.env['ir.model'].search([('model', '=', 'slide.channel')])
        # whitelist = self._get_whitelist_config()

        # Add courses with whitelisted fields only
        for course in self.course_ids:
            course_elem = ET.SubElement(root, 'course', id=str(course.id))

            # Export only whitelisted fields
            for field in ir_model_id.field_id:
                field_config = self._get_field_config(field.name)
                if field_config is not None:
                    try:
                        field_value = course[field.name]
                        self._export_field_value(course_elem, field, field_value, course, field_config,
                                                 parent_record=course)
                    except Exception as e:
                        _logger.warning(f"Error processing field {field.name}: {str(e)}")

        # Format with proper indentation using minidom
        rough_string = ET.tostring(root, encoding='utf-8')
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="    ", encoding='utf-8').decode('utf-8')

        _logger.info("XML generated successfully with formatting")
        return pretty_xml

    def _export_field_value(self, parent_elem, field, field_value, record, field_config=None, parent_record=None):
        if field.ttype in ['boolean', 'char', 'text', 'float', 'integer', 'selection', 'html', 'monetary', 'binary', 'image']:
            try:
                field_elem = ET.SubElement(parent_elem, 'field', name=field.name)

                if field.ttype in ['binary'] and field_value:
                    text_value = str(field_value)
                    if text_value.startswith("b'") and text_value.endswith("'"):
                        text_value = text_value[2:-1]  # Strip b' and trailing '
                    field_elem.text = text_value
                else:
                    field_elem.text = str(field_value) if field_value is not False else ''

            except Exception as e:
                _logger.warning(f"Failed to export field {field.name}: {str(e)}")

        elif field.ttype == 'date':
            try:
                field_elem = ET.SubElement(parent_elem, 'field', name=field.name)
                field_elem.text = str(field_value) if field_value else ''
            except Exception as e:
                _logger.warning(f"Failed to export field {field.name}: {str(e)}")

        elif field.ttype == 'datetime':
            try:
                field_elem = ET.SubElement(parent_elem, 'field', name=field.name)
                if field_value:
                    datetime_str = str(field_value)
                    if '.' in datetime_str:
                        datetime_str = datetime_str.split('.')[0]
                    field_elem.text = datetime_str
                else:
                    field_elem.text = ''
            except Exception as e:
                _logger.warning(f"Failed to export field {field.name}: {str(e)}")

        elif field.ttype == 'many2one':
            if field_value:
                # Check if this is pointing back to the parent record (inverse relation)
                if parent_record and field_value.id == parent_record.id and field_value._name == parent_record._name:
                    # Skip - this will be set automatically on import via one2many command
                    _logger.debug(f"Skipping inverse many2one field: {field.name}")
                    return
                elif isinstance(field_config, list):
                    # Export full record data for creation
                    self._export_many2one_with_data(parent_elem, field, field_value, field_config)
                else:
                    # Just export reference
                    external_id = field_value.get_external_id()
                    if external_id:
                        keys, values = list(external_id.items())[0]
                        ref_value = values if values else f"{field_value._name}-{field_value.id}"
                    else:
                        ref_value = f"{field_value._name}-{field_value.id}"

                    ET.SubElement(parent_elem, 'field', name=field.name, ref=ref_value)

        # Many2many fields
        elif field.ttype == 'many2many':
            if isinstance(field_config, list):
                self._export_many2many_with_data(parent_elem, field, field_value, field_config)
            else:
                m2m_values = []
                for val in field_value:
                    external_id = val.get_external_id()
                    if external_id and external_id.get(val.id):
                        m2m_values.append(f"(4, ref('{external_id[val.id]}'))")

                if m2m_values:
                    ET.SubElement(parent_elem, 'field', name=field.name, eval="[%s]" % ','.join(m2m_values))

        # One2many fields
        elif field.ttype == 'one2many':
            if isinstance(field_config, list):
                self._export_one2many_records(parent_elem, field, field_value, field_config, record)

    def _export_many2one_with_data(self, parent_elem, field, record, nested_fields):
        if not record:
            return

        # Get external ID if exists
        external_id = record.get_external_id()
        ref_value = None
        if external_id and external_id.get(record.id):
            ref_value = external_id[record.id]

        field_elem = ET.SubElement(parent_elem, 'field', name=field.name)

        # Create record element with both id and ref (if available)
        record_attrs = {'model': record._name} # 'id': str(record.id)
        if ref_value:
            record_attrs['ref'] = ref_value

        record_elem = ET.SubElement(field_elem, 'record', **record_attrs)

        # Export nested fields
        ir_model_id = self.env['ir.model'].search([('model', '=', record._name)])
        for nested_field_name in nested_fields:
            if isinstance(nested_field_name, dict):
                # Handle nested relations
                for nf_name, nf_config in nested_field_name.items():
                    nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nf_name)
                    if nested_field:
                        nested_value = record[nf_name]
                        self._export_field_value(record_elem, nested_field[0], nested_value, record, nf_config)
            else:
                nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nested_field_name)
                if nested_field:
                    nested_value = record[nested_field_name]
                    self._export_field_value(record_elem, nested_field[0], nested_value, record, True)

    def _export_many2many_with_data(self, parent_elem, field, records, nested_fields):
        if not records:
            return

        field_elem = ET.SubElement(parent_elem, 'field', name=field.name)

        for record in records:
            # Get external ID if exists
            external_id = record.get_external_id()
            ref_value = None
            if external_id and external_id.get(record.id):
                ref_value = external_id[record.id]

            # Create record element with both id and ref (if available)
            record_attrs = {'model': record._name} # 'id': str(record.id)
            if ref_value:
                record_attrs['ref'] = ref_value

            record_elem = ET.SubElement(field_elem, 'record', **record_attrs)

            # Export nested fields
            ir_model_id = self.env['ir.model'].search([('model', '=', record._name)])
            for nested_field_name in nested_fields:
                nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nested_field_name)
                if nested_field:
                    nested_value = record[nested_field_name]
                    self._export_field_value(record_elem, nested_field[0], nested_value, record, True)

    def _export_one2many_records(self, parent_elem, field, records, nested_fields, parent_record=None):
        if not records:
            return

        # Get model info for the related records
        related_model = field.relation
        ir_model_id = self.env['ir.model'].search([('model', '=', related_model)])

        # Create container for one2many records
        o2m_container = ET.SubElement(parent_elem, 'field', name=field.name)

        for record in records:
            # Get external ID if exists
            external_id = record.get_external_id()
            ref_value = None
            if external_id and external_id.get(record.id):
                ref_value = external_id[record.id]

            # Create record element with both id and ref (if available)
            record_attrs = {'model': related_model} # , 'id': str(record.id)
            if ref_value:
                record_attrs['ref'] = ref_value

            record_elem = ET.SubElement(o2m_container, 'record', **record_attrs)

            # Export configured fields only
            for nested_field_name in nested_fields:
                if isinstance(nested_field_name, dict):
                    # Handle nested relations
                    for nf_name, nf_config in nested_field_name.items():
                        nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nf_name)
                        if nested_field:
                            nested_value = record[nf_name]
                            self._export_field_value(record_elem, nested_field[0], nested_value, record, nf_config,
                                                     parent_record)
                else:
                    nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nested_field_name)
                    if nested_field:
                        nested_value = record[nested_field_name]
                        self._export_field_value(record_elem, nested_field[0], nested_value, record, True,
                                                 parent_record)

    def action_import(self):
        if not self.data_file:
            raise UserError("Please select a file to import.")

        try:
            xml_content = base64.b64decode(self.data_file)
            root = ET.fromstring(xml_content)

            imported_count = 0
            for course_elem in root.findall('course'):
                course_data = self._parse_record_fields(course_elem)

                new_course = self.env['slide.channel'].create(course_data)

                imported_count += 1
                _logger.info("Imported course: %s (ID: %s)", new_course.name, new_course.id)

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
            _logger.error("Import failed: %s", str(e), exc_info=True)
            raise UserError(f"Import failed: {str(e)}")

    def _parse_record_fields(self, record_elem):
        data = {}

        # Get model name to check field types
        model_name = record_elem.get('model')
        ir_model = None
        if model_name:
            ir_model = self.env['ir.model'].search([('model', '=', model_name)], limit=1)

        for field_elem in record_elem.findall('field'):
            field_name = field_elem.get('name')

            try:
                # Check if field has nested record(s) - means it's a relation
                nested_records = field_elem.findall('record')

                if nested_records:
                    # Has nested records - create child records
                    commands = []
                    for nested_record in nested_records:
                        child_data = self._parse_record_fields(nested_record)
                        if child_data:
                            commands.append((0, 0, child_data))

                    data[field_name] = commands if commands else False

                elif field_elem.get('ref'):
                    # Has ref attribute = many2one reference
                    ref = field_elem.get('ref')
                    data[field_name] = self._resolve_reference(ref)

                elif field_elem.get('eval'):
                    # Has eval attribute = many2many with eval syntax
                    eval_str = field_elem.get('eval')
                    data[field_name] = self._parse_many2many_eval(eval_str)

                else:
                    # Simple field with text value
                    text_value = field_elem.text

                    if not text_value:
                        # Empty field - skip it
                        continue

                    # Check if this is a binary/image field
                    is_binary = False
                    if ir_model:
                        field_obj = ir_model.field_id.filtered(lambda f: f.name == field_name)
                        if field_obj and field_obj.ttype in ['binary']:
                            is_binary = True

                    # Binary fields - keep as base64 string (already encoded)
                    if is_binary:
                        data[field_name] = text_value
                        continue

                    # Try to infer type from content for other fields
                    if text_value in ['True', 'False']:
                        data[field_name] = text_value == 'True'
                    elif text_value.replace('.', '', 1).replace('-', '', 1).isdigit():
                        # Could be int or float
                        if '.' in text_value:
                            data[field_name] = float(text_value)
                        else:
                            data[field_name] = int(text_value)
                    else:
                        # String value
                        data[field_name] = text_value

            except Exception as e:
                _logger.warning(f"Failed to import field {field_name}: {str(e)}", exc_info=True)

        return data

    def _resolve_reference(self, ref):
        if not ref:
            return False
        try:
            record = self.env.ref(ref, raise_if_not_found=False)
            if record:
                return record.id
        except:
            pass

        if '-' in ref:
            parts = ref.rsplit('-', 1)
            if len(parts) == 2:
                model_name, record_id = parts
                try:
                    record = self.env[model_name].browse(int(record_id))
                    if record.exists():
                        return record.id
                except:
                    pass

        _logger.warning(f"Could not resolve reference: {ref}")
        return False

    def _parse_many2many(self, eval_str):
        commands = []
        refs = re.findall(r"ref\('([^']+)'\)", eval_str)

        for ref in refs:
            record_id = self._resolve_reference(ref)
            if record_id:
                commands.append((4, record_id, 0))

        return commands if commands else False

    def _parse_one2many(self, field_elem):
        commands = []

        for record_elem in field_elem.findall('record'):
            # Parse all fields of the child record
            child_data = self._parse_record_fields(record_elem)

            # Create command to create the child record
            if child_data:
                commands.append((0, 0, child_data))

        return commands if commands else False
