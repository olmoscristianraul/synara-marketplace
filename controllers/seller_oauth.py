# -*- coding: utf-8 -*-
import logging
import secrets
import requests
from urllib.parse import quote_plus

from werkzeug.utils import redirect as werkzeug_redirect
from dateutil.relativedelta import relativedelta

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class SellerOAuthController(http.Controller):
    """Handles MercadoPago OAuth flow for marketplace sellers."""

    def _get_seller_partner(self):
        user = request.env.user
        if user._is_public():
            return False
        partner = user.partner_id
        if partner.is_marketplace_seller:
            return partner
        return False

    @http.route(
        ['/mi/marketplace/mercadopago/conectar'],
        type='http', auth='user', website=True,
    )
    def seller_connect_mercadopago(self, **kwargs):
        partner = self._get_seller_partner()
        if not partner:
            return request.redirect('/mi/marketplace/registro')

        IrConfig = request.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('synara_mp.mp_client_id')
        redirect_uri = IrConfig.get_param('synara_mp.mp_redirect_uri')
        if not redirect_uri:
            redirect_uri = (
                request.httprequest.host_url.rstrip('/')
                + '/marketplace/mercadopago/oauth/callback'
            )

        if not client_id:
            request.session['marketplace_profile_error'] = (
                'Falta configurar el Client ID de MercadoPago en Ajustes.'
            )
            return request.redirect('/mi/marketplace/perfil')

        state = secrets.token_urlsafe(16)
        request.session['marketplace_mp_oauth_state'] = state

        auth_url = (
            'https://auth.mercadopago.com.ar/authorization'
            f'?response_type=code&client_id={client_id}'
            f'&redirect_uri={quote_plus(redirect_uri)}'
            f'&state={state}&platform_id=mp&scope=offline_access%20payments'
        )
        response = werkzeug_redirect(auth_url)
        response.autocorrect_location_header = False
        return response

    @http.route(
        ['/marketplace/mercadopago/oauth/callback'],
        type='http', auth='user', website=True,
    )
    def mercadopago_oauth_callback(self, **kwargs):
        partner = self._get_seller_partner()
        if not partner:
            return request.redirect('/mi/marketplace/registro')

        expected_state = request.session.pop('marketplace_mp_oauth_state', False)
        returned_state = kwargs.get('state')
        if not expected_state or returned_state != expected_state:
            request.session['marketplace_profile_error'] = (
                'No pudimos validar la respuesta de MercadoPago.'
            )
            return request.redirect('/mi/marketplace/perfil')

        code = kwargs.get('code')
        if not code:
            request.session['marketplace_profile_error'] = (
                'MercadoPago no devolvió el código de autorización.'
            )
            return request.redirect('/mi/marketplace/perfil')

        IrConfig = request.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('synara_mp.mp_client_id')
        client_secret = IrConfig.get_param('synara_mp.mp_client_secret')
        redirect_uri = IrConfig.get_param('synara_mp.mp_redirect_uri')
        if not redirect_uri:
            redirect_uri = (
                request.httprequest.host_url.rstrip('/')
                + '/marketplace/mercadopago/oauth/callback'
            )

        if not client_secret:
            request.session['marketplace_profile_error'] = (
                'Falta configurar el Client Secret de MercadoPago.'
            )
            return request.redirect('/mi/marketplace/perfil')

        payload = {
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
        }
        try:
            response = requests.post(
                'https://api.mercadopago.com/oauth/token',
                data=payload,
                timeout=30,
            )
        except requests.RequestException as exc:
            _logger.exception('Error communicating with MercadoPago: %s', exc)
            request.session['marketplace_profile_error'] = (
                'No pudimos comunicarnos con MercadoPago. Intenta nuevamente.'
            )
            return request.redirect('/mi/marketplace/perfil')

        if not response.ok:
            _logger.error('MercadoPago rejected authorization: %s', response.text)
            request.session['marketplace_profile_error'] = (
                'MercadoPago rechazó la autorización. Verifica tu cuenta.'
            )
            return request.redirect('/mi/marketplace/perfil')

        data = response.json()
        expires_in = data.get('expires_in') or 0
        
        access_token = data.get('access_token')
        refresh_token = data.get('refresh_token')
        user_id = str(data.get('user_id') or '')
        
        # Intentar obtener el email del usuario de MP
        user_email = False
        if access_token:
            try:
                user_info_resp = requests.get(
                    'https://api.mercadopago.com/users/me',
                    headers={'Authorization': f'Bearer {access_token}'},
                    timeout=10
                )
                if user_info_resp.ok:
                    user_email = user_info_resp.json().get('email')
            except Exception as e:
                _logger.warning('Could not fetch MP user info: %s', e)

        partner.sudo().write({
            'mp_seller_access_token': access_token,
            'mp_seller_refresh_token': refresh_token,
            'mp_seller_user_id': user_id,
            'mp_seller_account_email': user_email,
            'mp_seller_token_expires_at': (
                fields.Datetime.now()
                + relativedelta(seconds=max(expires_in - 60, 0))
            ),
            'mp_seller_account_status': 'connected',
            'seller_onboarding_state': 'active',
        })
        request.session['marketplace_profile_flash'] = (
            '¡Tu cuenta de MercadoPago quedó conectada! Ya podés vender.'
        )
        return request.redirect('/mi/marketplace/perfil')

    @http.route(
        ['/mi/marketplace/mercadopago/desvincular'],
        type='http', auth='user', website=True,
    )
    def seller_disconnect_mercadopago(self, **kwargs):
        partner = self._get_seller_partner()
        if not partner:
            return request.redirect('/mi/marketplace/registro')
        
        partner.sudo().write({
            'mp_seller_access_token': False,
            'mp_seller_refresh_token': False,
            'mp_seller_user_id': False,
            'mp_seller_account_email': False,
            'mp_seller_token_expires_at': False,
            'mp_seller_account_status': 'not_connected',
            'seller_onboarding_state': 'pending_mp',
        })
        request.session['marketplace_profile_flash'] = 'Cuenta de Mercado Pago desvinculada.'
        
        redirect_url = request.httprequest.referrer or '/mi/marketplace/perfil'
        return request.redirect(redirect_url)
