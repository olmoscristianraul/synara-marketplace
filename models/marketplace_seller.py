# -*- coding: utf-8 -*-
import logging
import requests

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_marketplace_seller = fields.Boolean(
        string='Es vendedor marketplace',
        default=False,
        tracking=True,
    )
    seller_onboarding_state = fields.Selection([
        ('draft', 'Borrador'),
        ('pending_mp', 'Pendiente de MercadoPago'),
        ('active', 'Activo'),
        ('suspended', 'Suspendido'),
    ], string='Estado vendedor', default='draft', tracking=True)
    seller_store_name = fields.Char(string='Nombre de tienda')
    seller_description = fields.Text(string='Descripción pública')
    seller_slug = fields.Char(
        string='Slug URL',
        copy=False,
        help='Identificador único para la URL pública del vendedor.',
    )
    seller_commission_percent = fields.Float(
        string='Comisión del vendedor (%)',
        default=0.0,
        help='Si es 0, se usa la comisión global configurada en Ajustes.',
    )
    seller_logo = fields.Image(
        string='Logo de tienda',
        max_width=512,
        max_height=512,
        attachment=True,
    )

    # ── MercadoPago OAuth ──
    mp_seller_user_id = fields.Char(
        string='MP User ID',
        copy=False,
        groups='base.group_system',
    )
    mp_seller_access_token = fields.Char(
        string='MP Access Token',
        copy=False,
        groups='base.group_system',
    )
    mp_seller_refresh_token = fields.Char(
        string='MP Refresh Token',
        copy=False,
        groups='base.group_system',
    )
    mp_seller_token_expires_at = fields.Datetime(
        string='MP Token expira',
        groups='base.group_system',
    )
    mp_seller_account_status = fields.Selection([
        ('not_connected', 'No conectado'),
        ('connected', 'Conectado'),
        ('error', 'Con error'),
    ], string='Estado Mercado Pago', default='not_connected', tracking=True)
    mp_seller_account_email = fields.Char(
        string='Email Mercado Pago',
        groups='base.group_system',
    )

    # ── Relaciones ──
    marketplace_product_ids = fields.One2many(
        'product.template',
        'marketplace_seller_id',
        string='Productos publicados',
    )
    marketplace_product_count = fields.Integer(
        string='Productos',
        compute='_compute_marketplace_counts',
        store=True,
    )
    marketplace_sale_count = fields.Integer(
        string='Ventas',
        compute='_compute_marketplace_counts',
        store=True,
    )
    marketplace_commission_line_ids = fields.One2many(
        'marketplace.commission.line',
        'seller_id',
        string='Líneas de comisión',
    )

    @api.depends(
        'marketplace_product_ids',
        'marketplace_commission_line_ids',
    )
    def _compute_marketplace_counts(self):
        for partner in self:
            partner.marketplace_product_count = len(partner.marketplace_product_ids)
            partner.marketplace_sale_count = len(partner.marketplace_commission_line_ids)

    # ── MercadoPago Token Refresh ──
    def _mp_seller_refresh_token_if_needed(self, force=False):
        """Refresh the seller's MP access token if expired or forced."""
        IrConfig = self.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('synara_mp.mp_client_id')
        client_secret = IrConfig.get_param('synara_mp.mp_client_secret')
        for partner in self:
            if not partner.mp_seller_refresh_token or not client_id or not client_secret:
                continue
            if (
                not force
                and partner.mp_seller_token_expires_at
                and partner.mp_seller_token_expires_at > fields.Datetime.now()
            ):
                continue
            payload = {
                'grant_type': 'refresh_token',
                'client_id': client_id,
                'client_secret': client_secret,
                'refresh_token': partner.mp_seller_refresh_token,
            }
            try:
                response = requests.post(
                    'https://api.mercadopago.com/oauth/token',
                    data=payload,
                    timeout=30,
                )
            except requests.RequestException as exc:
                _logger.exception('Error refreshing MP token for seller %s: %s', partner.id, exc)
                partner.sudo().write({'mp_seller_account_status': 'error'})
                continue
            if response.ok:
                data = response.json()
                expires_in = data.get('expires_in') or 0
                partner.sudo().write({
                    'mp_seller_access_token': data.get('access_token'),
                    'mp_seller_refresh_token': data.get('refresh_token') or partner.mp_seller_refresh_token,
                    'mp_seller_token_expires_at': fields.Datetime.now() + relativedelta(
                        seconds=max(expires_in - 60, 0)
                    ),
                    'mp_seller_account_status': 'connected',
                })
            else:
                _logger.error(
                    'MP token refresh failed for seller %s: %s',
                    partner.id,
                    response.text,
                )
                partner.sudo().write({'mp_seller_account_status': 'error'})

    # ── Onboarding Actions ──
    def action_activate_seller(self):
        for partner in self.filtered(lambda p: p.is_marketplace_seller):
            if partner.mp_seller_account_status != 'connected':
                raise UserError(_(
                    'El vendedor %(name)s debe conectar su cuenta de MercadoPago antes de activarse.',
                    name=partner.display_name,
                ))
            partner.write({'seller_onboarding_state': 'active'})

    def action_suspend_seller(self):
        self.filtered('is_marketplace_seller').write({
            'seller_onboarding_state': 'suspended',
        })

    def action_reactivate_seller(self):
        for partner in self.filtered(lambda p: p.is_marketplace_seller and p.seller_onboarding_state == 'suspended'):
            if partner.mp_seller_account_status != 'connected':
                raise UserError(_(
                    'El vendedor %(name)s debe tener MercadoPago conectado para reactivarse.',
                    name=partner.display_name,
                ))
            partner.write({'seller_onboarding_state': 'active'})

    def action_view_seller_orders(self):
        self.ensure_one()
        return {
            'name': _('Ventas del Vendedor'),
            'type': 'ir.actions.act_window',
            'res_model': 'marketplace.commission.line',
            'view_mode': 'list,form',
            'domain': [('seller_id', '=', self.id)],
            'context': {'default_seller_id': self.id},
        }

    def _marketplace_get_effective_commission(self):
        """Returns the effective commission % for this seller."""
        self.ensure_one()
        if self.seller_commission_percent:
            return self.seller_commission_percent
        IrConfig = self.env['ir.config_parameter'].sudo()
        default = IrConfig.get_param('synara_mp.default_commission', '22.0')
        try:
            return float(default)
        except (TypeError, ValueError):
            return 22.0
