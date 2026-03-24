import logging
import secrets
import requests
from urllib.parse import quote_plus

from werkzeug.utils import redirect as werkzeug_redirect

from dateutil.relativedelta import relativedelta

from odoo import http, fields
from odoo.http import request

from .portal_base import PhotographerPortalMixin

_logger = logging.getLogger(__name__)


class PhotographerSettingsController(PhotographerPortalMixin, http.Controller):
    @http.route(
        ['/mi/fotoapp/perfil'],
        type='http',
        auth='user',
        website=True,
        methods=['GET', 'POST']
    )
    def photographer_profile_settings(self, **post):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied

        flash = request.session.pop('fotoapp_profile_flash', False)
        error = request.session.pop('fotoapp_profile_error', False)
        form_errors = []
        IrConfig = request.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('fotoapp.mp_client_id')
        client_secret = IrConfig.get_param('fotoapp.mp_client_secret')
        redirect_uri = IrConfig.get_param('fotoapp.mp_redirect_uri')
        if not redirect_uri:
            redirect_uri = request.httprequest.host_url.rstrip('/') + '/fotoapp/mercadopago/oauth/callback'
        mp_available = bool(client_id and client_secret)
        profile_fields = (
            'photographer_first_name', 'photographer_last_name', 'photographer_bio',
            'portfolio_url', 'photo_reservoir_url', 'instagram_account',
            'phone_whatsapp', 'payout_preference', 'payout_account',
            'bank_name_or_wallet', 'bank_alias', 'cbu_cvu'
        )
        form_state = {field: (partner[field] or '') for field in profile_fields}
        if request.httprequest.method == 'POST':
            update_vals, form_errors, form_state = self._prepare_profile_update(partner, post, profile_fields)
            if not form_errors and update_vals:
                partner.sudo().write(update_vals)
                request.session['fotoapp_profile_flash'] = 'Los cambios en tu perfil se guardaron correctamente.'
                return request.redirect('/mi/fotoapp/perfil')
        payout_options = request.env['res.partner']._fields['payout_preference'].selection
        values = {
            'partner': partner,
            'active_menu': 'profile',
            'flash': flash,
            'error': error,
            'form_errors': form_errors,
            'mp_available': mp_available,
            'connect_url': '/mi/fotoapp/mercadopago/conectar' if mp_available else False,
            'mp_redirect_uri': redirect_uri,
            'form_state': form_state,
            'payout_options': payout_options,
        }
        return request.render('fotoapp.photographer_profile_settings', values)

    @http.route(
        ['/mi/fotoapp/mercadopago/conectar'],
        type='http',
        auth='user',
        website=True,
    )
    # Esta función maneja la ruta para que un fotógrafo conecte su cuenta de Mercado Pago con la plataforma FotoApp.
    # Primero, asegura que el usuario actual es un fotógrafo autorizado. Si no lo es, devuelve una respuesta de acceso denegado.
    # Luego, obtiene los parámetros de configuración necesarios (Client ID y Redirect URI) desde la configuración del sistema.
    # Si falta el Client ID, guarda un mensaje de error en la sesión y redirige al fotógrafo a su página de perfil.
    # Si todo está en orden, genera un estado aleatorio para la seguridad de la autorización OAuth y lo guarda en la sesión.
    # Finalmente, construye la URL de autorización de Mercado Pago con los parámetros necesarios y redirige al fotógrafo a esa URL para que pueda autorizar la conexión.
    def photographer_connect_mercadopago(self, **kwargs):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied
        IrConfig = request.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('fotoapp.mp_client_id')
        redirect_uri = IrConfig.get_param('fotoapp.mp_redirect_uri')
        if not redirect_uri:
            redirect_uri = request.httprequest.host_url.rstrip('/') + '/fotoapp/mercadopago/oauth/callback'
        if not client_id:
            request.session['fotoapp_profile_error'] = 'Falta configurar el Client ID de Mercado Pago.'
            return request.redirect('/mi/fotoapp/perfil')
        state = secrets.token_urlsafe(16)
        request.session['fotoapp_mp_oauth_state'] = state
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
        ['/fotoapp/mercadopago/oauth/callback'],
        type='http',
        auth='user',
        website=True,
    )
    def mercadopago_oauth_callback(self, **kwargs):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied
        expected_state = request.session.pop('fotoapp_mp_oauth_state', False)
        returned_state = kwargs.get('state')
        if not expected_state or returned_state != expected_state:
            request.session['fotoapp_profile_error'] = 'No pudimos validar la respuesta de Mercado Pago.'
            return request.redirect('/mi/fotoapp/perfil')

        code = kwargs.get('code')
        if not code:
            request.session['fotoapp_profile_error'] = 'Mercado Pago no devolvió el código de autorización.'
            return request.redirect('/mi/fotoapp/perfil')

        IrConfig = request.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('fotoapp.mp_client_id')
        client_secret = IrConfig.get_param('fotoapp.mp_client_secret')
        redirect_uri = IrConfig.get_param('fotoapp.mp_redirect_uri')
        if not redirect_uri:
            redirect_uri = request.httprequest.host_url.rstrip('/') + '/fotoapp/mercadopago/oauth/callback'

        if not client_secret:
            request.session['fotoapp_profile_error'] = 'Falta configurar el Client Secret de Mercado Pago.'
            return request.redirect('/mi/fotoapp/perfil')

        payload = {
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
        }
        try:
            response = requests.post('https://api.mercadopago.com/oauth/token', data=payload, timeout=30)
        except requests.RequestException as exc:
            _logger.exception('Error comunicando con Mercado Pago: %s', exc)
            request.session['fotoapp_profile_error'] = 'No pudimos comunicarnos con Mercado Pago. Intenta nuevamente.'
            return request.redirect('/mi/fotoapp/perfil')

        if not response.ok:
            _logger.error('Mercado Pago rechazó la autorización: %s', response.text)
            request.session['fotoapp_profile_error'] = 'Mercado Pago rechazó la autorización. Verifica tu cuenta.'
            return request.redirect('/mi/fotoapp/perfil')

        data = response.json()
        expires_in = data.get('expires_in') or 0
        partner.sudo().write({
            'mp_access_token': data.get('access_token'),
            'mp_refresh_token': data.get('refresh_token'),
            'mp_user_id': str(data.get('user_id') or ''),
            'mp_account_email': data.get('user_email'),
            'mp_token_expires_at': fields.Datetime.now() + relativedelta(seconds=max(expires_in - 60, 0)),
            'mp_account_status': 'connected',
        })
        request.session['fotoapp_profile_flash'] = '¡Tu cuenta de Mercado Pago quedó conectada!'
        return request.redirect('/mi/fotoapp/perfil')

    def _prepare_profile_update(self, partner, payload, profile_fields):
        errors = []
        update_vals = {}
        form_state = {}

        def _clean_value(key):
            return (payload.get(key) or '').strip()

        url_fields = {
            'portfolio_url': 'Portfolio',
            'photo_reservoir_url': 'Reservorio de fotos',
        }
        max_bio_length = 2000

        for field in profile_fields:
            value = _clean_value(field)
            form_state[field] = value
            if field in url_fields:
                if value and not value.lower().startswith(('http://', 'https://')):
                    errors.append('El campo %s debe comenzar con http:// o https://.' % url_fields[field])
                update_vals[field] = value or False
            elif field == 'payout_preference':
                allowed = {code for code, _label in partner._fields['payout_preference'].selection}
                if value and value not in allowed:
                    errors.append('El método de cobro seleccionado no es válido.')
                else:
                    update_vals[field] = value or 'mercadopago'
                    form_state[field] = value or 'mercadopago'
            elif field == 'photographer_bio':
                if value and len(value) > max_bio_length:
                    errors.append('Tu biografía no puede superar %s caracteres.' % max_bio_length)
                update_vals[field] = value or False
            else:
                update_vals[field] = value or False

        if not errors:
            # Avoid writing default payout preference twice
            if not payload.get('payout_preference'):
                update_vals['payout_preference'] = update_vals.get('payout_preference') or partner.payout_preference or 'mercadopago'

        return update_vals, errors, form_state

    @http.route(
        ['/mi/fotoapp/configuracion/marca-agua'],
        type='http',
        auth='user',
        website=True,
        methods=['GET', 'POST']
    )
    def photographer_watermark_settings(self, **post):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied

        success_message = request.session.pop('fotoapp_watermark_success', False)
        errors = []
        values = {
            'partner': partner,
            'active_menu': 'settings',
            'errors': errors,
            'success': success_message,
        }

        if request.httprequest.method == 'POST':
            update_vals = {}
            watermark_file = request.httprequest.files.get('watermark_image')
            remove_image = post.get('remove_watermark') == '1'

            if watermark_file and watermark_file.filename:
                encoded = self._prepare_cover_image(watermark_file)
                if encoded:
                    update_vals['watermark_image'] = encoded
                else:
                    errors.append('No se pudo procesar la imagen cargada. Intenta con otro archivo.')
            elif remove_image:
                update_vals['watermark_image'] = False

            opacity_raw = post.get('watermark_opacity')
            scale_raw = post.get('watermark_scale')

            try:
                opacity_value = int(opacity_raw)
            except (TypeError, ValueError):
                opacity_value = None
            if opacity_value is None or opacity_value < 0 or opacity_value > 100:
                errors.append('La opacidad debe ser un número entre 0 y 100.')
            else:
                update_vals['watermark_opacity'] = opacity_value

            try:
                scale_value = float(scale_raw)
            except (TypeError, ValueError):
                scale_value = None
            if scale_value is None or scale_value <= 0:
                errors.append('La escala debe ser un número mayor a 0.')
            else:
                scale_value = max(0.05, min(scale_value, 1.0))
                update_vals['watermark_scale'] = scale_value

            if not errors and update_vals:
                partner.sudo().write(update_vals)
                request.session['fotoapp_watermark_success'] = 'Configuración de marca de agua guardada correctamente.'
                return request.redirect('/mi/fotoapp/configuracion/marca-agua')

        return request.render('fotoapp.photographer_watermark_settings', values)
