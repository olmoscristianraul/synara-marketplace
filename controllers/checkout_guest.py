# -*- coding: utf-8 -*-
"""
Guest checkout defaults for FotoApp.

This controller forces minimal address/billing data for anonymous carts so the
checkout can proceed with only email.
"""

import logging
import re

from odoo import http, _
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale
from odoo.addons.website_sale.controllers.payment import PaymentPortal as WebsiteSalePaymentPortal

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_logger = logging.getLogger(__name__)


class FotoappWebsiteSale(WebsiteSale):
	@http.route(['/shop/address'], type='http', auth="public", website=True, sitemap=False)
	def address(self, **kw):
		order = request.website.sale_get_order()
		is_guest = self._fotoapp_is_guest_checkout(order)

		if request.httprequest.method == 'POST':
			return self.shop_address_submit(**kw)

		if is_guest and order and order.partner_id:
			_logger.info("Guest checkout address: order %s ya tiene partner %s, redirigiendo a payment", order.id, order.partner_id.id)
			return request.redirect('/shop/payment')

		# Llama a la implementación base de WebsiteSale (shop_address)
		return super().shop_address(**kw)
	
	def _fotoapp_is_guest_checkout(self, order_sudo):
		return bool(order_sudo and order_sudo._is_anonymous_cart())
	
	## esta funcion fue copiada y adaptada de website_sale/controllers/main.py
	## porque es la unica forma de modificar el comportamiento del checkout guest
	## sin modificar el core de odoo.
	## el objetivo es forzar ciertos campos en la direccion de facturacion
	def _first(self, model, domain, order=None):
		registry = request.env.registry
		if model not in registry:
			return request.env['res.partner'].browse()
		env = request.env.sudo()
		return env[model].search(domain, limit=1, order=order or 'id')

	def _fotoapp_validate_single_photographer(self, order_sudo):
		photo_lines = order_sudo.order_line.filtered(lambda l: l.foto_photographer_id)
		photographers = set(photo_lines.mapped('foto_photographer_id').ids)
		if len(photographers) > 1:
			request.session['website_sale_cart_warning'] = _(
				'No está permitido agregar fotos de varios fotógrafos al carrito. Separá los carritos por favor.'
			)
			return request.redirect('/shop/cart')
		return None


	def _validate_address_values(
		self,
		address_values,
		partner_sudo,
		address_type,
		use_delivery_as_billing,
		required_fields,
		is_main_address,
		**kwargs,
	):
		# VALORES POR DEFECTO PARA CHECKOUT DE INVITADOS
		data = {
				'name': 'Guest Buyer',
				'company_name': 'Guest Buyer',
				'city': 'Rosario',
				'zip': '2000',
				'phone': '2477610123',
				'vat': '43026589',
				'street': 'Calle falsa 123',
				'street2': '4-1',
				'consumidor_final': False,
				'dni_type': False,
				'country_id': False,
				'state_id': False,
			}
		order_sudo = request.website.sale_get_order()
		is_guest = self._fotoapp_is_guest_checkout(order_sudo)

		if is_guest:
			# BUSCAR LOS VALORES
			_logger.info("FotoApp Guest Checkout - Applying guest defaults for address: %s", data)
			consumidor_final = request.env['l10n_ar.afip.responsibility.type'].search([('code', '=', '5')], limit=1)
			dni_type = request.env['l10n_latam.identification.type'].search([('name', '=', 'DNI')], limit=1)
			country_id = request.env['res.country'].search([('code', '=', 'AR')], limit=1)
			state_id = request.env['res.country.state'].search([('code', '=', 'S')], limit=1)

			data = {
				'name': 'Guest Buyer',
				'company_name': 'Guest Buyer',
				'city': 'Rosario',
				'zip': '2000',
				'phone': '2477610123',
				'vat': '43026589',
				'street': 'Calle falsa 123',
				'street2': '4-1',
				'consumidor_final': consumidor_final,
				'dni_type': dni_type,
				'country_id': country_id,
				'state_id': state_id,
			}
			_logger.info(" LOGGGGGGG FotoApp Guest Checkout - Guest address data: %s", data)

			# INYECTAR LOS VALORES A LA FUERZA
			if consumidor_final:
				address_values['l10n_ar_afip_responsibility_type_id'] = int(consumidor_final.id)
			if dni_type:
				address_values['l10n_latam_identification_type_id'] = int(dni_type.id)
			if country_id:
				address_values['country_id'] = int(country_id.id)
			if state_id:
				address_values['state_id'] = int(state_id.id)
			address_values['name'] = data['name']
			address_values['company_name'] = data['company_name']
			address_values['city'] = data['city']
			address_values['zip'] = data['zip']
			address_values['phone'] = data['phone']
			address_values['vat'] = data['vat']
			address_values['street'] = data['street']
			address_values['street2'] = data['street2']
			_logger.info(" LOG LOG LOG FotoApp Guest Checkout - Guest address after data: %s", address_values)
			

			email = (address_values.get('email') or '').strip()
			if not email or not EMAIL_RE.match(email):
				return set(), {'email'}, [_('Ingresá un correo válido.')]

			required_fields = 'email'
			use_delivery_as_billing = True


			_logger.info(" FotoApp Guest Checkout - Final call to super with address values: %s", address_values)
			_logger.info(" FotoApp Guest Checkout - Final call to super with partner_sudo: %s", partner_sudo)
			_logger.info(" FotoApp Guest Checkout - Final call to super with address_type: %s", address_type)
			_logger.info(" FotoApp Guest Checkout - Final call to super with use_delivery_as_billing: %s", use_delivery_as_billing)
			_logger.info(" FotoApp Guest Checkout - Final call to super with required_fields: %s", required_fields)
			_logger.info(" FotoApp Guest Checkout - Final call to super with is_main_address: %s", is_main_address)	
			_logger.info(" FotoApp Guest Checkout - Final call to super with kwargs: %s", kwargs)
			return super()._validate_address_values(
			address_values,
			partner_sudo,
			address_type,
			use_delivery_as_billing,
			required_fields,
			is_main_address,
			**kwargs,
		)

		return super()._validate_address_values(
			address_values,
			partner_sudo,
			address_type,
			use_delivery_as_billing,
			required_fields,
			is_main_address,
			**kwargs,
		)

	def _check_cart(self, order_sudo):
		redir = super()._check_cart(order_sudo)
		if redir:
			return redir
		return self._fotoapp_validate_single_photographer(order_sudo)

	def shop_address_submit(self, **post):
		order = request.website.sale_get_order()
		is_guest = self._fotoapp_is_guest_checkout(order)

		if is_guest:
			email = (post.get('email') or '').strip() or (order.partner_id.email if order and order.partner_id else '')
			if not email or not EMAIL_RE.match(email):
				email = 'guest@example.com'

			partner = request.env['res.partner'].sudo().search([('email', '=', email)], limit=1)
			if not partner:
				partner = request.env['res.partner'].sudo().create({
					'name': 'Guest Buyer',
					'email': email,
				})

			if order:
				order_vals = {
					'partner_id': partner.id,
					'partner_invoice_id': partner.id,
					'partner_shipping_id': partner.id,
				}
				order.sudo().write(order_vals)
				_logger.info("Guest checkout submit: order %s bound to partner %s, redirecting to payment", order.id, partner.id)

			return request.redirect('/shop/payment')

		return super().shop_address_submit(**post)

	@http.route(['/shop/payment'], type='http', auth='public', website=True, sitemap=False)
	def shop_payment(self, **post):
		order = request.website.sale_get_order()
		is_guest = self._fotoapp_is_guest_checkout(order)

		if is_guest and order:
			# Asegura partner en el pedido
			if not order.partner_id:
				guest = request.website.user_id.sudo().partner_id
				order.sudo().write({
					'partner_id': guest.id,
					'partner_invoice_id': guest.id,
					'partner_shipping_id': guest.id,
				})
			# Renderiza directamente la página de pago sin redirecciones intermedias
			values = self._get_shop_payment_values(order, **post)
			values['fotoapp_guest'] = True
			return request.render("website_sale.payment", values)

		return super().shop_payment(**post)

# Mantiene la clase WebsiteSale, pero la ruta /shop/payment/transaction la sobreescribimos
# en FotoappPaymentPortal más abajo (hereda de website_sale.controllers.payment.PaymentPortal).
	
	# @http.route(['/shop/address'], type='http', auth="public", website=True, sitemap=False, csrf=False)
	# def address(self, **kw):
	# 	"""
	# 	Guest checkout: solo email -> crea/actualiza partner guest, asigna partner_* al pedido,
	# 	y redirige a /shop/payment.
	# 	"""
	# 	order = request.website.sale_get_order()
	# 	is_guest = self._fotoapp_is_guest_checkout(order)

	# 	if is_guest and request.httprequest.method == 'POST':
	# 		email = (kw.get('email') or '').strip()
	# 		if not email or not EMAIL_RE.match(email):
	# 			_logger.info("Guest checkout: email inválido: %s", email)
	# 			return request.render("website_sale.address", {
	# 				'error': _("Ingresá un correo válido."),
	# 				'order': order,
	# 			})

	# 		consumidor_final = request.env['l10n_ar.afip.responsibility.type'].sudo().search([('code', '=', '5')], limit=1)
	# 		dni_type = request.env['l10n_latam.identification.type'].sudo().search([('name', '=', 'DNI')], limit=1)
	# 		country = request.env['res.country'].sudo().search([('code', '=', 'AR')], limit=1)

	# 		state = request.env['res.country.state'].sudo().search([
	# 			('country_id', '=', country.id),
	# 			('name', 'ilike', 'Santa Fe'),
	# 		], limit=1) if country else request.env['res.country.state']

	# 		partner = request.env['res.partner'].sudo().search([('email', '=', email)], limit=1)
	# 		if not partner:
	# 			partner = request.env['res.partner'].sudo().create({
	# 				'name': 'Guest Buyer',
	# 				'email': email,
	# 			})

	# 		vals = {}
	# 		if country:
	# 			vals['country_id'] = country.id
	# 		if state:
	# 			vals['state_id'] = state.id
	# 		if consumidor_final:
	# 			vals['l10n_ar_afip_responsibility_type_id'] = consumidor_final.id
	# 		if dni_type:
	# 			vals['l10n_latam_identification_type_id'] = dni_type.id

	# 		if vals:
	# 			partner.sudo().write(vals)

	# 		if order:
	# 			order.sudo().write({
	# 				'partner_id': partner.id,
	# 				'partner_invoice_id': partner.id,
	# 				'partner_shipping_id': partner.id,
	# 			})
	# 			_logger.info("Guest checkout: order %s -> partner %s", order.id, partner.id)

	# 		return request.redirect('/shop/payment')
	# 	return super().address(**kw)


class FotoappPaymentPortal(WebsiteSalePaymentPortal):
	@http.route('/shop/payment/transaction/<int:order_id>', type='json', auth='public', website=True)
	def shop_payment_transaction(self, order_id, access_token, **kwargs):
		"""Captura guest_email antes de delegar en el flujo estándar de website_sale."""
		order_sudo = request.env['sale.order'].sudo().browse(order_id).exists()
		email = (
			kwargs.pop('guest_email', '')
			or request.httprequest.form.get('guest_email')
			or ''
		).strip()
		if not email and order_sudo and order_sudo.partner_id:
			email = (order_sudo.partner_id.email or '').strip()

		_logger.info(
			"FotoApp shop_payment_transaction - guest email: %s | kwargs keys: %s | order_id: %s",
			email,
			list(kwargs.keys()),
			order_id,
		)

		if order_sudo and email and EMAIL_RE.match(email):
			partner = order_sudo.partner_id
			if partner:
				partner.sudo().write({'email': email})
				order_sudo.sudo().write({
					'partner_invoice_id': partner.id,
					'partner_shipping_id': partner.id,
				})
		else:
			_logger.warning(
				"FotoApp shop_payment_transaction - missing/invalid guest email, skipping partner update. Order: %s",
				order_sudo and order_sudo.id,
			)

		return super().shop_payment_transaction(order_id, access_token, **kwargs)