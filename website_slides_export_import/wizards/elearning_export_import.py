import base64
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
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
        
        # Validate the XML can be parsed
        try:
            ET.fromstring(xml_content.encode('utf-8'))
            _logger.info("XML validation successful")
        except ET.ParseError as e:
            _logger.error(f"Generated XML is invalid: {str(e)}")
            raise UserError(f"Failed to generate valid XML: {str(e)}")

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
            'tag_ids': [
                'name',
                'color',
                {
                    'group_id': ['name']
                }
            ],

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

        # Phase 1: Collect all attachments from HTML content
        slide_attachments, modified_html_map = self._collect_attachments_from_courses()
        
        # Phase 2: Create attachments section in XML
        if slide_attachments:
            self._create_attachments_section(root, slide_attachments)
        
        # Phase 3: Export course data with modified HTML
        self._export_courses_data(root, modified_html_map)

        # Format with proper indentation
        return self._format_xml(root)

    def _collect_attachments_from_courses(self):
        """
        First pass: Extract and deduplicate images from all slides.
        Returns: (slide_attachments, modified_html_map)
        """
        slide_attachments = {}
        modified_html_map = {}  # {slide_id: modified_html}
        
        for course in self.course_ids:
            for slide in course.slide_ids:
                slide_ref = f"slide_{slide.id}"
                
                if slide.html_content:
                    # Extract images from HTML
                    modified_html, _ = self._extract_images_from_html(
                        slide.html_content, 
                        slide_ref,
                        slide_attachments
                    )
                    # Store modified HTML in dictionary
                    modified_html_map[slide.id] = modified_html
                else:
                    modified_html_map[slide.id] = slide.html_content
        
        return slide_attachments, modified_html_map

    def _create_attachments_section(self, root, slide_attachments):
        """
        Create the <attachments> section in XML with all unique images.
        """
        attachments_elem = ET.SubElement(root, 'attachments')
        
        for att_id, att_data in slide_attachments.items():
            att_elem = ET.SubElement(
                attachments_elem, 
                'attachment',
                id=att_id,
                checksum=att_data['checksum']
            )
            
            # Add attachment fields
            ET.SubElement(att_elem, 'field', name='name').text = att_data['name']
            # Ensure datas is a string, not bytes
            datas_value = att_data['datas']
            if isinstance(datas_value, bytes):
                datas_value = datas_value.decode('utf-8')
            ET.SubElement(att_elem, 'field', name='datas').text = datas_value
            ET.SubElement(att_elem, 'field', name='mimetype').text = att_data['mimetype']
            
            # Add slides that use this attachment
            if att_data['slides']:
                slides_elem = ET.SubElement(att_elem, 'slides')
                for slide_ref in sorted(att_data['slides']):
                    ET.SubElement(slides_elem, 'slide', ref=slide_ref)

    def _export_courses_data(self, root, modified_html_map):
        ir_model_id = self.env['ir.model'].search([('model', '=', 'slide.channel')])

        for course in self.course_ids:
            course_elem = ET.SubElement(root, 'course', id=str(course.id))

            # Export only whitelisted fields
            for field in ir_model_id.field_id:
                field_config = self._get_field_config(field.name)
                if field_config is not None:
                    try:
                        field_value = course[field.name]
                        self._export_field_value(
                            course_elem, 
                            field, 
                            field_value, 
                            course, 
                            field_config,
                            parent_record=course,
                            modified_html_map=modified_html_map
                        )
                    except Exception as e:
                        _logger.warning(f"Error processing field {field.name}: {str(e)}")

    def _format_xml(self, root):
        ET.indent(root, space="    ", level=0)
        # Convert to bytes with UTF-8 encoding and XML declaration
        xml_bytes = ET.tostring(root, encoding='utf-8', method='xml', xml_declaration=True)
        # Decode to string for storage
        xml_string = xml_bytes.decode('utf-8')
        _logger.info("XML generated successfully with formatting")
        return xml_string

    def _export_field_value(self, parent_elem, field, field_value, record, field_config=None, parent_record=None, modified_html_map=None):
        if field.ttype in ['boolean', 'char', 'text', 'float', 'integer', 'selection', 'html', 'monetary', 'binary', 'image']:
            try:
                field_elem = ET.SubElement(parent_elem, 'field', name=field.name)

                # Special handling for html_content - use modified HTML if available
                if field.name == 'html_content' and modified_html_map and record.id in modified_html_map:
                    text_value = modified_html_map[record.id] or ''
                    # Ensure it's a string
                    field_elem.text = str(text_value) if text_value else ''
                elif field.ttype in ['binary'] and field_value:
                    text_value = str(field_value)
                    if text_value.startswith("b'") and text_value.endswith("'"):
                        text_value = text_value[2:-1]  # Strip b' and trailing '
                    field_elem.text = text_value
                else:
                    # Ensure proper string conversion
                    if field_value is False or field_value is None:
                        field_elem.text = ''
                    else:
                        field_elem.text = str(field_value)

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
                self._export_one2many_records(parent_elem, field, field_value, field_config, record, modified_html_map)

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
                if isinstance(nested_field_name, dict):
                    # Handle nested relations (e.g., {'group_id': ['name']})
                    for nf_name, nf_config in nested_field_name.items():
                        nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nf_name)
                        if nested_field:
                            nested_value = record[nf_name]
                            self._export_field_value(record_elem, nested_field[0], nested_value, record, nf_config)
                else:
                    # Simple field name
                    nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nested_field_name)
                    if nested_field:
                        nested_value = record[nested_field_name]
                        self._export_field_value(record_elem, nested_field[0], nested_value, record, True)

    def _export_one2many_records(self, parent_elem, field, records, nested_fields, parent_record=None, modified_html_map=None):
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
                                                     parent_record, modified_html_map)
                else:
                    nested_field = ir_model_id.field_id.filtered(lambda f: f.name == nested_field_name)
                    if nested_field:
                        nested_value = record[nested_field_name]
                        self._export_field_value(record_elem, nested_field[0], nested_value, record, True,
                                                 parent_record, modified_html_map)

    def action_import(self):
        if not self.data_file:
            raise UserError("Please select a file to import.")

        try:
            xml_content = base64.b64decode(self.data_file)
            
            # Try to parse XML with better error reporting
            try:
                root = ET.fromstring(xml_content)
            except ET.ParseError as e:
                # Log the problematic area
                _logger.error(f"XML Parse Error: {str(e)}")
                
                # Save XML to temp file for debugging
                import tempfile
                try:
                    with tempfile.NamedTemporaryFile(mode='wb', suffix='.xml', delete=False, prefix='odoo_import_error_') as f:
                        f.write(xml_content)
                        temp_path = f.name
                    _logger.error(f"Problematic XML saved to: {temp_path}")
                except Exception as save_error:
                    _logger.error(f"Could not save XML to temp file: {str(save_error)}")
                
                # Try to show context around the error
                context_msg = ""
                try:
                    xml_text = xml_content.decode('utf-8')
                    lines = xml_text.split('\n')
                    error_line = int(str(e).split('line ')[1].split(',')[0]) if 'line ' in str(e) else 0
                    
                    if error_line > 0:
                        start = max(0, error_line - 5)
                        end = min(len(lines), error_line + 5)
                        context = '\n'.join(f"{i+1}: {lines[i]}" for i in range(start, end))
                        _logger.error(f"Context around error:\n{context}")
                        context_msg = f"\n\nContext around line {error_line}:\n{context}"
                except Exception as ctx_error:
                    _logger.error(f"Could not extract context: {str(ctx_error)}")
                
                raise UserError(f"Failed to parse XML file: {str(e)}{context_msg}")

            # Import attachments and build mapping
            attachment_mapping = self._import_attachments(root)

            # Import courses with attachment URL replacement and linking
            imported_count = 0
            
            for course_elem in root.findall('course'):
                course_data = self._parse_record_fields(course_elem, attachment_mapping)
                new_course = self.env['slide.channel'].create(course_data)

                # Link attachments to slides (optimized - only check slides with HTML)
                for slide in new_course.slide_ids:
                    if slide.html_content:
                        # Find and link attachments used in this slide
                        for att_id, att_info in attachment_mapping.items():
                            if att_info['url'] in slide.html_content and not att_info['attachment'].res_id:
                                att_info['attachment'].write({
                                    'res_model': 'slide.slide',
                                    'res_id': slide.id,
                                })
                                break  # Only link to first slide that uses it

                imported_count += 1


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

    def _import_attachments(self, root):
        """
        Import attachments from XML and create ir.attachment records.
        Returns: dict mapping {att_id: {'url': web_url, 'attachment': record}}
        """
        attachment_mapping = {}
        
        attachments_elem = root.find('attachments')
        if attachments_elem is None:
            _logger.info("No attachments section found in XML")
            return attachment_mapping
        
        for att_elem in attachments_elem.findall('attachment'):
            att_id = att_elem.get('id')
            checksum = att_elem.get('checksum')
            
            # Parse attachment fields
            att_data = {}
            for field_elem in att_elem.findall('field'):
                field_name = field_elem.get('name')
                att_data[field_name] = field_elem.text or ''
            
            attachment = None
            
            # First try: Check by checksum (most reliable)
            if checksum:
                existing_att = self.env['ir.attachment'].search([
                    ('checksum', '=', checksum)
                ], limit=1)
                
                if existing_att:
                    attachment = existing_att
            
            # Second try: Check by name and mimetype (fallback)
            if not attachment:
                existing_att = self.env['ir.attachment'].search([
                    ('name', '=', att_data.get('name', '')),
                    ('mimetype', '=', att_data.get('mimetype', '')),
                    ('checksum', '=', checksum)  # Still check checksum to be safe
                ], limit=1)
                
                if existing_att:
                    attachment = existing_att
            
            # Create new if not found
            if not attachment:
                attachment = self.env['ir.attachment'].create({
                    'name': att_data.get('name', 'imported_image'),
                    'datas': att_data.get('datas', ''),
                    'mimetype': att_data.get('mimetype', 'image/png'),
                    # Don't set res_model/res_id yet - will be linked to slides later
                })
            
            # Map placeholder to URL and attachment record
            attachment_mapping[att_id] = {
                'url': f"/web/image/{attachment.id}",
                'attachment': attachment
            }
        
        return attachment_mapping


    def _parse_record_fields(self, record_elem, attachment_mapping=None):
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
                    # Has nested records - could be One2many or Many2one
                    # Check field type to determine how to handle
                    field_type = None
                    if ir_model:
                        field_obj = ir_model.field_id.filtered(lambda f: f.name == field_name)
                        if field_obj:
                            field_type = field_obj.ttype
                    
                    if field_type == 'many2one':
                        # Many2one: create or find the related record and use its ID
                        nested_record = nested_records[0]  # Many2one only has one record
                        child_data = self._parse_record_fields(nested_record, attachment_mapping)
                        
                        if child_data:
                            # Get the model from the nested record
                            child_model = nested_record.get('model')
                            if child_model:
                                # Try to find existing record by name (or other unique fields)
                                existing = None
                                if 'name' in child_data:
                                    existing = self.env[child_model].search([('name', '=', child_data['name'])], limit=1)
                                
                                if existing:
                                    data[field_name] = existing.id
                                else:
                                    # Create new record
                                    new_record = self.env[child_model].create(child_data)
                                    data[field_name] = new_record.id
                    else:
                        # One2many or Many2many: use command format (0, 0, data)
                        commands = []
                        for nested_record in nested_records:
                            child_data = self._parse_record_fields(nested_record, attachment_mapping)
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
                    
                    # Replace attachment placeholders with actual URLs
                    if attachment_mapping and '{{ATT:' in text_value:
                        text_value = self._replace_attachment_placeholders(text_value, attachment_mapping)

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


    def _extract_images_from_html(self, html_content, slide_ref, slide_attachments):
        """
        Extract images from HTML content and add to slide attachments.
        Only extracts the current/converted image (from src), not originals.
        Returns: (modified_html, unused_dict)
        """
        if not html_content:
            return html_content, {}
        
        modified_html = html_content
        
        # Pattern to match Odoo image URLs ONLY in src attributes (not data-original-src or other data- attributes)
        # Uses negative lookbehind to ensure 'src' is not preceded by a word character (like 'data-original-')
        # This matches: src="/web/image/123..." or src='/web/image/123...' but NOT data-original-src="..."
        pattern = r'(?<![\w-])src=["\'](/web/image/(\d+)(?:-[a-f0-9]+)?(?:/[^"\']*)?)["\']'
        
        matches = list(re.finditer(pattern, html_content))
        _logger.debug(f"Found {len(matches)} image URLs in src attributes for slide {slide_ref}")
        
        processed_urls = set()  # Track processed URLs to avoid duplicates
        
        for match in matches:
            _logger.debug(f"Regex match: full={match.group(0)}, url={match.group(1)}, id={match.group(2)}")
            original_url = match.group(1)  # The full URL without quotes
            
            # Skip if we already processed this URL
            if original_url in processed_urls:
                continue
            
            # Skip website theme images (e.g., /web/image/website.something)
            if 'website.' in original_url:
                _logger.debug(f"Skipping website theme image: {original_url}")
                continue
            
            attachment_id = int(match.group(2))  # The ID is now in group 2
            
            try:
                # Fetch the attachment from database
                attachment = self.env['ir.attachment'].browse(attachment_id)
                
                if not attachment.exists():
                    _logger.warning(f"Attachment {attachment_id} not found for slide {slide_ref}")
                    continue
                
                # Get attachment data
                if not attachment.datas:
                    _logger.warning(f"Attachment {attachment_id} has no data")
                    continue
                
                # Calculate checksum for deduplication
                binary_data = base64.b64decode(attachment.datas)
                checksum = hashlib.sha256(binary_data).hexdigest()
                
                # Generate unique attachment ID
                att_id = f"att_{checksum[:12]}"
                
                # Check if this attachment already exists (deduplication)
                if att_id not in slide_attachments:
                    # New attachment - add to collection
                    _logger.debug(f"Adding new attachment to export: {att_id} (ID: {attachment_id}, name: {attachment.name}, mimetype: {attachment.mimetype})")
                    slide_attachments[att_id] = {
                        'checksum': checksum,
                        'name': attachment.name or 'image',
                        'datas': attachment.datas,
                        'mimetype': attachment.mimetype or 'image/png',
                        'slides': []
                    }
                else:
                    _logger.debug(f"Attachment {att_id} already in export, skipping (ID: {attachment_id})")
                
                # Track that this slide uses this attachment
                if slide_ref not in slide_attachments[att_id]['slides']:
                    slide_attachments[att_id]['slides'].append(slide_ref)
                
                # Replace URL with placeholder
                placeholder = f"{{{{ATT:{att_id}}}}}"
                modified_html = modified_html.replace(original_url, placeholder)
                
                processed_urls.add(original_url)
                
            except Exception as e:
                _logger.error(f"Error processing attachment {attachment_id}: {str(e)}")
                continue
        
        return modified_html, {}


    def _replace_attachment_placeholders(self, text_value, attachment_mapping):
        """
        Replace attachment placeholders {{ATT:att_id}} with actual URLs.
        """
        modified_text = text_value
        
        # Find all placeholders in the format {{ATT:att_xxxxx}}
        pattern = r'\{\{ATT:([^}]+)\}\}'
        matches = re.finditer(pattern, text_value)
        
        for match in matches:
            placeholder = match.group(0)  # Full placeholder like {{ATT:att_xxxxx}}
            att_id = match.group(1)  # Just the att_xxxxx part
            
            if att_id in attachment_mapping:
                # Extract URL from mapping (now it's a dict with 'url' and 'attachment')
                actual_url = attachment_mapping[att_id]['url']
                modified_text = modified_text.replace(placeholder, actual_url)
                _logger.debug(f"Replaced {placeholder} with {actual_url}")
            else:
                _logger.warning(f"Attachment placeholder {placeholder} not found in mapping")
        
        return modified_text


