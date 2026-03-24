# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    synara_mp_client_id = fields.Char(
        string='MercadoPago Client ID',
        config_parameter='synara_mp.mp_client_id',
    )
    synara_mp_client_secret = fields.Char(
        string='MercadoPago Client Secret',
        config_parameter='synara_mp.mp_client_secret',
    )
    synara_mp_redirect_uri = fields.Char(
        string='Redirect URI para OAuth',
        config_parameter='synara_mp.mp_redirect_uri',
        help='URL completa para el callback de OAuth de MercadoPago. '
             'Termina con /marketplace/mercadopago/oauth/callback',
    )
    synara_mp_default_commission = fields.Float(
        string='Comisión por defecto (%)',
        config_parameter='synara_mp.default_commission',
        default=22.0,
    )
    synara_mp_gateway_journal_id = fields.Many2one(
        'account.journal',
        string='Diario de pagos MercadoPago',
        domain="[('type', 'in', ('bank', 'cash'))]",
        config_parameter='synara_mp.gateway_journal_id',
        help='Diario bancario para registrar cobros de MercadoPago.',
    )
    synara_mp_require_approval = fields.Boolean(
        string='Requiere aprobación de productos',
        config_parameter='synara_mp.require_approval',
        default=False,
        help='Si está activo, los productos creados por vendedores requieren aprobación antes de publicarse.',
    )
