# -*- coding: utf-8 -*-
from odoo import models


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    def _build_request_headers(self, method, endpoint, payload, **kwargs):
        """Inject seller's access token as Authorization header for MP marketplace."""
        headers = super()._build_request_headers(method, endpoint, payload, **kwargs)
        seller_token = kwargs.get('seller_access_token')
        if self.code == 'mercado_pago' and seller_token:
            headers = dict(headers or {})
            headers['Authorization'] = f'Bearer {seller_token}'
        return headers
