import logging
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError

_logger = logging.getLogger(__name__)

_INTERVALS = {
    'hours': lambda interval: relativedelta(hours=interval),
    'days': lambda interval: relativedelta(days=interval),
    'weeks': lambda interval: relativedelta(days=7*interval),
    'months': lambda interval: relativedelta(months=interval),
    'now': lambda interval: relativedelta(hours=0),
}

class SlideMail(models.Model):
    _name = 'slide.mail'
    _rec_name = "slide_channel_id"
    _description = 'E-Learning Automated Mailing'

    slide_channel_id = fields.Many2one(comodel_name="slide.channel")
    scheduled_date = fields.Datetime('Schedule Date', compute='_compute_scheduled_date', store=True)
    interval_nbr = fields.Integer('Interval', default=1)
    interval_unit = fields.Selection([
        ('now', 'Immediately'),
        ('hours', 'Hours'), ('days', 'Days'),
        ('weeks', 'Weeks'), ('months', 'Months')],
        string='Unit', default='hours', required=True)
    interval_type = fields.Selection([
        ('after_sub', 'After each registration'),
        ('before_event', 'Reminder'),
        ('after_event', 'Completion')],
        string='Trigger ', default="before_event", required=True)
    mail_done = fields.Boolean("Sent", copy=False, readonly=True)
    partner_id = fields.Many2one(comodel_name="res.partner")
    mail_count_done = fields.Integer('# Sent', copy=False, readonly=True)
    template_ref = fields.Reference(string='Template', ondelete={'mail.template': 'cascade'}, required=True, selection=[('mail.template', 'Mail')])
    sequence = fields.Integer('Display order')
    mail_state = fields.Selection(
        [('running', 'Running'), ('scheduled', 'Scheduled'), ('sent', 'Sent')],
        string='Global communication Status', compute='_compute_mail_state')
    
    tmp_start_date = fields.Date()
    tmp_end_date = fields.Date()

    @api.model_create_multi
    def create(self, vals_list):
        slide_mail_ids = super(SlideMail,self).create(vals_list)

        for slide_mail_id in slide_mail_ids:
            if slide_mail_id.interval_type == "after_sub" and slide_mail_id.interval_unit == "now":
                if slide_mail_id.partner_id:
                    _logger.error(f"{slide_mail_id.partner_id.name=}")
                    slide_mail_id._send_mail(slide_mail_id.partner_id)
                    slide_mail_id.mail_count_done += 1 
                slide_mail_id.mail_done = True

        return slide_mail_ids

    @api.depends('interval_type', 'mail_done')
    def _compute_mail_state(self):
        for scheduler in self:
            # registrations based
            if scheduler.interval_type == 'after_sub':
                scheduler.mail_state = 'running'
            # global event based
            elif scheduler.mail_done:
                scheduler.mail_state = 'sent'
            else:
                scheduler.mail_state = 'scheduled'

    # 'calendar_event_id.start', 'calendar_event_id.stop',
    @api.depends( 'interval_type', 'interval_unit', 'interval_nbr')
    def _compute_scheduled_date(self):
        for scheduler in self:
            if scheduler.interval_type == 'after_sub':
                date, sign = scheduler.create_date, 1
            elif scheduler.interval_type == 'before_event':
                date, sign = scheduler.tmp_start_date, -1
            else:
                date, sign = scheduler.tmp_end_date, 1

            scheduler.scheduled_date = date + _INTERVALS[scheduler.interval_unit](sign * scheduler.interval_nbr) if date else False

    @api.model
    def cron_run(self):
        before_event = self.search([("interval_type","=","before_event"),("scheduled_date", "<=", fields.Datetime.now()),("calendar_event_id.start", ">=", fields.Datetime.now()),("mail_done", "=", False)])
        after_event = self.search([("interval_type","=","after_event"),("scheduled_date", "<=",fields.Datetime.now()),("calendar_event_id.stop", "<=", fields.Datetime.now()),("mail_done", "=", False)])
        after_sub = self.search([("interval_type","=","after_sub"),("scheduled_date", "<=",fields.Datetime.now()),("interval_unit", "!=", "now"),("mail_done", "=", False)])

        slide_mail_ids = before_event + after_event + after_sub

        for slide_mail_id in slide_mail_ids:
            if slide_mail_id.partner_id:
                slide_mail_id._send_mail(slide_mail_id.partner_id)
                slide_mail_id.mail_count_done += 1 
                slide_mail_id.mail_done = True

    def _send_mail(self,partner_id):
        """ Mail action: send mail to attendees """
        if partner_id.email:
            author = partner_id
        elif partner_id.parent_id.email:
            author = partner_id.parent_id
        else:
            author = self.env.ref('base.user_root').partner_id

        composer_values = {
            'composition_mode': 'mass_mail',
            'force_send': False,
            'model': self._name,
            'record_name': False,
            'res_ids': [self.id],
            'template_id': self.template_ref.id,
        }

        composer_values['author_id'] = author.id
        composer_values['email_from'] = self.template_ref.email_from or author.email_formatted
        composer = self.env['mail.compose.message'].create(composer_values)

        composer.with_context(mail_composer_force_partners=False)._action_send_mail()