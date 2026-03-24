# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    marketplace_seller_id = fields.Many2one(
        'res.partner',
        string='Vendedor marketplace',
        related='product_id.product_tmpl_id.marketplace_seller_id',
        store=True,
        readonly=True,
    )
