# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleSubscriptionTemplate(models.Model):
    _inherit = 'sale.subscription.template'

    fotoapp_plan_id = fields.Many2one(
        'fotoapp.plan',
        string='Plan FotoApp',
        copy=False,
        help='Identifica si la plantilla pertenece a un plan de fotógrafos.',
    )
    _sql_constraints = [
        (
            'fotoapp_plan_unique',
            'unique(fotoapp_plan_id)',
            'Cada plan FotoApp solo puede vincularse a una plantilla específica.',
        )
    ]
