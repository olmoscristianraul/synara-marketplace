# -*- coding: utf-8 -*-
from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        users = super().create(vals_list)
        users._fotoapp_ensure_partner_defaults()
        return users

    def _fotoapp_ensure_partner_defaults(self):
        partners = self.mapped('partner_id')
        if not partners:
            return
        not_flagged = partners.filtered(lambda partner: partner and not partner.is_photographer)
        if not_flagged:
            not_flagged.write({'is_photographer': True})
        photographers = partners.filtered('is_photographer')
        if photographers:
            photographers._ensure_default_photo_plan()
