# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round

from odoo.addons.payment_mercado_pago import const


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

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
        string='Monto vendedor',
        currency_field='currency_id',
        copy=False,
    )

    def _send_api_request(self, method, endpoint, *, params=None, data=None, json=None, **kwargs):
        """Inject seller's access token as Authorization header for MP API calls."""
        self.ensure_one()
        self._marketplace_sync_metadata_from_orders()
        if self.provider_code == 'mercado_pago' and self.marketplace_seller_id:
            kwargs.setdefault(
                'seller_access_token',
                self._marketplace_get_seller_token(),
            )
        return super()._send_api_request(
            method, endpoint,
            params=params, data=data, json=json,
            **kwargs,
        )

    def _mercado_pago_prepare_preference_request_payload(self):
        """Inject marketplace_fee into the MercadoPago preference payload."""
        self._marketplace_sync_metadata_from_orders()
        payload = super()._mercado_pago_prepare_preference_request_payload()
        if self.marketplace_platform_amount:
            payload['marketplace_fee'] = self._marketplace_convert_amount(
                self.marketplace_platform_amount,
            )
        metadata = payload.setdefault('metadata', {})
        metadata.update({
            'marketplace_seller_id': self.marketplace_seller_id.id if self.marketplace_seller_id else False,
            'marketplace_commission_percent': self.marketplace_commission_percent,
            'marketplace_sale_orders': ','.join(self.sale_order_ids.mapped('name')),
        })
        
        # Enforce HTTPS for back_urls and notification_url
        # MercadoPago rejects auto_return if URLs are not HTTPS (often the case behind proxies).
        if 'back_urls' in payload:
            for k, v in payload['back_urls'].items():
                if v and v.startswith('http://'):
                    payload['back_urls'][k] = v.replace('http://', 'https://', 1)
        if payload.get('notification_url') and payload['notification_url'].startswith('http://'):
            payload['notification_url'] = payload['notification_url'].replace('http://', 'https://', 1)
            
        return payload

    def _marketplace_get_seller_token(self):
        """Return the seller's MP access token, refreshing if needed."""
        self.ensure_one()
        partner = self.marketplace_seller_id.sudo()
        if not partner:
            raise ValidationError(_(
                'No se pudo identificar el vendedor asociado al pedido.'
            ))
        partner._mp_seller_refresh_token_if_needed()
        access_token = partner.mp_seller_access_token
        if not access_token:
            raise ValidationError(_(
                'El vendedor %(name)s debe conectar su cuenta de Mercado Pago antes de cobrar.',
                name=partner.display_name,
            ))
        if partner.mp_seller_account_status != 'connected':
            raise ValidationError(_(
                'La cuenta de Mercado Pago de %(name)s no está lista (estado: %(status)s).',
                name=partner.display_name,
                status=dict(
                    partner._fields['mp_seller_account_status'].selection
                ).get(partner.mp_seller_account_status, partner.mp_seller_account_status),
            ))
        return access_token

    def _marketplace_convert_amount(self, amount):
        """Round amount to the currency's MercadoPago decimal precision."""
        currency_code = self.currency_id.name
        decimal_places = const.CURRENCY_DECIMALS.get(currency_code)
        if decimal_places is not None:
            return float_round(amount, precision_digits=decimal_places, rounding_method='DOWN')
        return amount

    def _marketplace_sync_metadata_from_orders(self):
        """Sync marketplace seller and commission data from linked sale orders."""
        for tx in self:
            if tx.marketplace_seller_id:
                continue
            orders = tx.sudo().sale_order_ids
            if not orders:
                continue
            sellers = orders.mapped('order_line.product_id.product_tmpl_id.marketplace_seller_id')
            if not sellers:
                continue
            seller_ids = set(sellers.ids)
            if len(seller_ids) > 1:
                continue  # Multi-seller — skip
            seller = sellers[:1]
            commission_percent = (
                orders[:1].marketplace_commission_percent
                or seller._marketplace_get_effective_commission()
            )
            amount_total = sum(orders.mapped('amount_total'))
            platform_amount = amount_total * (commission_percent or 0.0) / 100.0
            seller_amount = amount_total - platform_amount
            write_vals = {
                'marketplace_seller_id': seller.id,
                'marketplace_commission_percent': commission_percent,
                'marketplace_platform_amount': platform_amount,
                'marketplace_seller_amount': seller_amount,
            }
            tx.write(write_vals)
            orders.write(write_vals)
