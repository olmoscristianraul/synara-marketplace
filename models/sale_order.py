# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    marketplace_seller_id = fields.Many2one(
        'res.partner',
        string='Vendedor marketplace',
        copy=False,
    )
    marketplace_commission_percent = fields.Float(
        string='Comisión marketplace (%)',
        copy=False,
    )
    marketplace_platform_amount = fields.Monetary(
        string='Comisión plataforma',
        currency_field='currency_id',
        copy=False,
    )
    marketplace_seller_amount = fields.Monetary(
        string='Monto para vendedor',
        currency_field='currency_id',
        copy=False,
    )
    marketplace_delivery_status = fields.Selection([
        ('pending', 'Pendiente de entrega'),
        ('shipped', 'En camino / Entregado'),
    ], string='Estado entrega marketplace', default='pending', copy=False)

    # ── Override para inyectar metadata en la transacción ──
    def _prepare_payment_transaction_vals(self, **kwargs):
        self._marketplace_ensure_single_seller()
        if len(self) == 1 and not self.marketplace_seller_id:
            seller = self._marketplace_detect_seller()
            if seller:
                self.sudo()._marketplace_apply_seller_metadata(seller)
                self.sudo()._marketplace_recompute_commission()
        vals = super()._prepare_payment_transaction_vals(**kwargs)
        if len(self) == 1 and self.marketplace_seller_id:
            vals.update({
                'marketplace_seller_id': self.marketplace_seller_id.id,
                'marketplace_commission_percent': self.marketplace_commission_percent,
                'marketplace_platform_amount': self.marketplace_platform_amount,
                'marketplace_seller_amount': self.marketplace_seller_amount,
            })
        return vals

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            if order.marketplace_seller_id:
                order._marketplace_create_commission_line()
                order._marketplace_notify_seller()
        return res

    # ── Internals ──
    def _marketplace_detect_seller(self):
        """Detect the single marketplace seller from order lines."""
        self.ensure_one()
        seller_lines = self.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id.marketplace_seller_id
        )
        if not seller_lines:
            return False
        sellers = seller_lines.mapped('product_id.product_tmpl_id.marketplace_seller_id')
        seller_ids = set(sellers.ids)
        if len(seller_ids) > 1:
            raise ValidationError(_(
                'El carrito contiene productos de distintos vendedores. '
                'Solo se permite un vendedor por pedido.'
            ))
        return sellers[:1]

    def _marketplace_ensure_single_seller(self):
        """Validate there's at most one marketplace seller per order."""
        for order in self:
            if order.state not in ('draft', 'sent'):
                continue
            seller_lines = order.order_line.filtered(
                lambda l: l.product_id.product_tmpl_id.marketplace_seller_id
            )
            if not seller_lines:
                continue
            sellers = seller_lines.mapped('product_id.product_tmpl_id.marketplace_seller_id')
            if len(set(sellers.ids)) > 1:
                raise ValidationError(_(
                    'El carrito contiene productos de distintos vendedores. '
                    'Solo se permite un vendedor por pedido.'
                ))
            seller = sellers[:1]
            if not order.marketplace_seller_id:
                order.sudo()._marketplace_apply_seller_metadata(seller)
                order.sudo()._marketplace_recompute_commission()

    def _marketplace_apply_seller_metadata(self, seller):
        """Apply seller and commission metadata to the order."""
        self.ensure_one()
        CommissionRule = self.env['marketplace.commission.rule']
        # Try to find a product to resolve category-based commission
        first_product = self.order_line.filtered(
            lambda l: l.product_id.product_tmpl_id.marketplace_seller_id
        )[:1].product_id.product_tmpl_id
        commission = CommissionRule.get_commission_for(seller, first_product)
        self.write({
            'marketplace_seller_id': seller.id,
            'marketplace_commission_percent': commission,
        })

    def _marketplace_recompute_commission(self):
        """Recalculate platform and seller amounts based on commission %."""
        for order in self:
            percent = (order.marketplace_commission_percent or 0.0) / 100.0
            platform_amount = (order.amount_total or 0.0) * percent
            seller_amount = (order.amount_total or 0.0) - platform_amount
            order.write({
                'marketplace_platform_amount': platform_amount,
                'marketplace_seller_amount': seller_amount,
            })

    def _marketplace_create_commission_line(self):
        """Create a commission.line record for this confirmed sale."""
        self.ensure_one()
        if not self.marketplace_seller_id:
            return
        self.env['marketplace.commission.line'].sudo().create({
            'seller_id': self.marketplace_seller_id.id,
            'sale_order_id': self.id,
            'sale_date': fields.Datetime.now(),
            'sale_amount': self.amount_total,
            'commission_percent': self.marketplace_commission_percent,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
        })

    def _marketplace_notify_seller(self):
        """Notify the seller about the new order via internal message."""
        self.ensure_one()
        seller = self.marketplace_seller_id
        if not seller:
            return
        body = _(
            '¡Nueva venta en el marketplace!<br/>'
            'Pedido: <b>%(order)s</b><br/>'
            'Total: <b>%(total)s %(currency)s</b><br/>'
            'Tu pago: <b>%(seller_amount)s %(currency)s</b><br/>'
            'Cliente: %(customer)s',
            order=self.name,
            total=self.amount_total,
            currency=self.currency_id.name,
            seller_amount=self.marketplace_seller_amount,
            customer=self.partner_id.display_name,
        )
        self.message_post(
            body=body,
            partner_ids=seller.ids,
            message_type='notification',
            subtype_xmlid='mail.mt_note',
        )
