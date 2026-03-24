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
    marketplace_promo_price = fields.Float(
        string='Precio promocional',
        help='Precio tachado para mostrar en oferta.',
    )
    marketplace_shipping_cost = fields.Float(
        string='Costo de envío',
        help='Costo de envío para este producto específico.',
    )
    marketplace_commission_percent = fields.Float(
        string='Comisión (%)',
        help='Comisión específica para este producto. Si es 0, se usa la del vendedor.',
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
