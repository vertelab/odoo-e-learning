from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class SlideChannelPartner(models.Model):
    _inherit = "slide.channel.partner"

    # booking_mail_calendar_ids = fields.One2many(comodel_name="booking.mail.calendar", inverse_name="calendar_event_id")

    @api.model_create_multi
    def create(self, vals_list):
        slide_channel_partner_ids = super(SlideChannelPartner,self).create(vals_list)

        for partner_id in self:
        
            self.env["slide.mail"].create({
                "partner_id": partner_id.id,
                "slide_channel_id": partner_id.slide_channel_id.id,
            })

        return slide_channel_partner_ids