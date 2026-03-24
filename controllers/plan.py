# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class FotoappPlanWebsite(http.Controller):

    @http.route('/planesfotografo', type='http', auth='public', website=True, sitemap=True)
    def fotoapp_plan_listing(self, **kw):
        Plan = request.env['fotoapp.plan'].sudo()
        plans = Plan.search([('website_published', '=', True)], order='sequence, monthly_fee desc, id')
        current_plan_id = False
        user = request.env.user
        if not user._is_public() and user.partner_id.plan_id:
            current_plan_id = user.partner_id.plan_id.id

        return request.render('fotoapp.fotoapp_plan_public_page', {
            'plans': plans,
            'current_plan_id': current_plan_id,
        })