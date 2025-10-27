from odoo import api, fields, models, tools, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression
from odoo.tools import is_html_empty


class SlideSlide(models.Model):
    _inherit = 'slide.slide'

    def _check_can_access(self):
        """Override to check course date access"""
        res = super(SlideSlide, self)._check_can_access()

        if self.channel_id:
            access_check = self.env['slide.channel']._check_course_date_access(
                self.channel_id.id
            )
            if not access_check['accessible']:
                return False

        return res
