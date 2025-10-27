# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http, _
from odoo.http import request
from odoo.addons.website_slides.controllers.main import WebsiteSlides


class WebsiteSlidesDateAccess(WebsiteSlides):
    def _check_channel_date_access(self, channel):
        """
        Check if channel is accessible based on start/end dates
        Returns access check result dict
        """
        return request.env['slide.channel']._check_course_date_access(channel.id)

    @http.route('/slides/slide/get_html_content', type='json', auth='public', website=True)
    def get_slide_html_content(self, slide_id):
        """Override to check date access before returning slide content"""
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get('error'):
            return fetch_res

        slide = fetch_res['slide']

        # Check date-based access
        access_check = self._check_channel_date_access(slide.channel_id)

        if not access_check['accessible']:
            return {
                'error': 'access_denied',
                'error_message': access_check['message']
            }

        # If accessible, proceed with normal flow
        return super(WebsiteSlidesDateAccess, self).get_slide_html_content(slide_id)

    @http.route(['/slides/slide/set_completed'], type='json', auth='public', website=True)
    def slide_set_completed(self, slide_id):
        """Override to check date access before marking slide as completed"""
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get('error'):
            return fetch_res

        slide = fetch_res['slide']

        # Check date-based access
        access_check = self._check_channel_date_access(slide.channel_id)

        if not access_check['accessible']:
            return {
                'error': 'access_denied',
                'error_message': access_check['message']
            }

        # If accessible, proceed with normal flow
        return super(WebsiteSlidesDateAccess, self).slide_set_completed(slide_id)

    @http.route(['/slides/slide/quiz/submit'], type='json', auth='public', website=True)
    def slide_quiz_submit(self, slide_id, answer_ids):
        """Override to check date access before submitting quiz"""
        fetch_res = self._fetch_slide(slide_id)
        if fetch_res.get('error'):
            return fetch_res

        slide = fetch_res['slide']

        # Check date-based access
        access_check = self._check_channel_date_access(slide.channel_id)

        if not access_check['accessible']:
            return {
                'error': 'access_denied',
                'error_message': access_check['message']
            }

        # If accessible, proceed with normal flow
        return super(WebsiteSlidesDateAccess, self).slide_quiz_submit(slide_id, answer_ids)

    @http.route('/slides/channel/check_access', type='json', auth='public', website=True)
    def channel_check_date_access(self, channel_id):
        """
        JSON endpoint to check if a channel is accessible based on dates
        Returns: {'accessible': bool, 'message': str, 'status': str}
        """
        try:
            channel = request.env['slide.channel'].browse(int(channel_id))
            if not channel.exists():
                return {
                    'accessible': False,
                    'message': _('Course not found'),
                    'status': 'error'
                }

            return self._check_channel_date_access(channel)
        except Exception as e:
            return {
                'accessible': False,
                'message': str(e),
                'status': 'error'
            }