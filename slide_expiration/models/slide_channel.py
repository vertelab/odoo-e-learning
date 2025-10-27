from odoo import api, fields, models, tools, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression
from odoo.tools import is_html_empty


class SlideChannel(models.Model):
    _inherit = 'slide.channel'

    start_date = fields.Date(string="Start Date", default=fields.Date.today)
    end_date = fields.Date(string="End Date")

    @api.model
    def _check_course_date_access(self, channel_id):
        """
        Check if the course is accessible based on current date/time
        Returns: dict with 'accessible' boolean and 'message' string
        """
        channel = self.browse(channel_id)
        now = fields.Datetime.now()

        result = {
            'accessible': True,
            'message': '',
            'status': 'active'
        }

        # Check if course has ended
        if channel.end_date and fields.Date.today() > channel.end_date:
            result['accessible'] = False
            result['status'] = 'ended'
            end_date_str = channel.end_date.strftime('%Y-%m-%d')
            result['message'] = _('This course ended on %s and is no longer accessible') % end_date_str

        return result

    def check_access_rights(self, operation, raise_exception=True):
        """Override to add date-based access control"""
        res = super(SlideChannel, self).check_access_rights(operation, raise_exception)

        if operation == 'read' and self:
            access_check = self._check_course_date_access(self.id)
            if not access_check['accessible']:
                if raise_exception:
                    raise AccessError(access_check['message'])
                return False
        return res


