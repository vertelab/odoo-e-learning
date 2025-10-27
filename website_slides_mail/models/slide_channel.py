from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class SlideChannelPartner(models.Model):
    _inherit = "slide.channel"

    slide_mail_ids = fields.One2many(comodel_name="slide.mail", inverse_name="slide_channel_id")

  