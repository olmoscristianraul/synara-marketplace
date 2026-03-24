# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    marketplace_seller_id = fields.Many2one(
        'res.partner',
        string='Vendedor marketplace',
        domain="[('is_marketplace_seller', '=', True)]",
        index=True,
        copy=False,
        tracking=True,
    )
    marketplace_approved = fields.Boolean(
        string='Aprobado para marketplace',
        default=False,
        tracking=True,
        help='Indica si un administrador aprobó este producto para publicación.',
    )
    marketplace_seller_store = fields.Char(
        string='Tienda',
        related='marketplace_seller_id.seller_store_name',
        store=True,
        readonly=True,
    )

    def action_marketplace_approve(self):
        """Admin approves product for marketplace publication."""
        self.write({
            'marketplace_approved': True,
            'website_published': True,
        })

    def action_marketplace_reject(self):
        """Admin rejects / unpublishes product."""
        self.write({
            'marketplace_approved': False,
            'website_published': False,
        })
