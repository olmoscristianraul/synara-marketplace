# -*- coding: utf-8 -*-
import base64
import logging
import re

from odoo import http, fields, _
from odoo.http import request

_logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SellerPortalController(http.Controller):
    """Portal controller for marketplace seller operations.

    Sellers are portal users. Product management is done by admins
    in the Odoo backend. The seller portal provides:
    - Registration + MercadoPago OAuth connection
    - Dashboard with sales summary
    - Order list and detail (to fulfill orders)
    - Commission history
    - Profile editing
    """

    def _get_seller_partner(self):
        """Return the current user's partner if it's a marketplace seller, else False."""
        user = request.env.user
        if user._is_public():
            return False
        partner = user.partner_id
        if partner.is_marketplace_seller:
            return partner
        return False

    def _ensure_seller(self):
        """Return (partner, None) or (False, redirect_response)."""
        partner = self._get_seller_partner()
        if partner:
            return partner, None
        return False, request.redirect('/mi/marketplace/registro')

    def _ensure_active_seller(self):
        """Ensure seller is active, return (partner, None) or (False, response)."""
        partner, denied = self._ensure_seller()
        if not partner:
            return False, denied
        if partner.seller_onboarding_state == 'suspended':
            return False, request.render('synara-marketplace.seller_suspended', {
                'partner': partner,
            })
        return partner, None

    # ── Registration ──
    @http.route(
        ['/mi/marketplace/registro'],
        type='http', auth='public', website=True,
        methods=['GET', 'POST'],
    )
    def seller_registration(self, **post):
        if request.env.user._is_public() and request.httprequest.method == 'GET':
            return request.render('synara-marketplace.seller_registration_form', {
                'errors': [],
            })

        if request.httprequest.method == 'POST':
            return self._process_registration(post)

        # Logged-in user — check if already a seller
        partner = self._get_seller_partner()
        if partner:
            return request.redirect('/mi/marketplace/dashboard')

        return request.render('synara-marketplace.seller_registration_form', {
            'errors': [],
        })

    def _process_registration(self, post):
        errors = []
        name = (post.get('name') or '').strip()
        email = (post.get('email') or '').strip()
        store_name = (post.get('store_name') or '').strip()
        phone = (post.get('phone') or '').strip()
        password = (post.get('password') or '').strip()

        if not name:
            errors.append('El nombre es obligatorio.')
        if not email or not EMAIL_RE.match(email):
            errors.append('Ingresá un correo electrónico válido.')
        if not store_name:
            errors.append('El nombre de la tienda es obligatorio.')
        if not password or len(password) < 6:
            errors.append('La contraseña debe tener al menos 6 caracteres.')

        if errors:
            return request.render('synara-marketplace.seller_registration_form', {
                'errors': errors,
                'values': post,
            })

        # Check if email already in use
        existing_user = request.env['res.users'].sudo().search(
            [('login', '=', email)], limit=1,
        )
        if existing_user:
            partner = existing_user.partner_id
            partner.sudo().write({
                'is_marketplace_seller': True,
                'seller_store_name': store_name,
                'seller_onboarding_state': 'pending_mp',
                'phone': phone or partner.phone,
            })
            return request.redirect('/web/login?redirect=/mi/marketplace/dashboard')

        existing_partner = request.env['res.partner'].sudo().search(
            [('email', '=', email)], limit=1,
        )
        partner = existing_partner or request.env['res.partner'].sudo().create({
            'name': name,
            'email': email,
            'phone': phone,
            'is_marketplace_seller': True,
            'seller_store_name': store_name,
            'seller_onboarding_state': 'pending_mp',
        })

        # Create portal user
        try:
            portal_group = request.env.ref('base.group_portal')
            request.env['res.users'].sudo().create({
                'name': name,
                'login': email,
                'password': password,
                'partner_id': partner.id,
                'groups_id': [(6, 0, [portal_group.id])],
            })
            partner.sudo().write({
                'is_marketplace_seller': True,
                'seller_store_name': store_name,
                'seller_onboarding_state': 'pending_mp',
            })
        except Exception as e:
            _logger.exception('Error creating seller portal user: %s', e)
            errors.append('Error al crear la cuenta. El email podría estar en uso.')
            return request.render('synara-marketplace.seller_registration_form', {
                'errors': errors,
                'values': post,
            })

        return request.redirect('/web/login?redirect=/mi/marketplace/dashboard')

    # ── Dashboard ──
    @http.route(
        ['/mi/marketplace/dashboard'],
        type='http', auth='user', website=True,
    )
    def seller_dashboard(self, **kw):
        partner, denied = self._ensure_seller()
        if not partner:
            return denied

        CommissionLine = request.env['marketplace.commission.line'].sudo()
        lines = CommissionLine.search([('seller_id', '=', partner.id)])
        total_sales = sum(lines.mapped('sale_amount'))
        total_commissions = sum(lines.mapped('commission_amount'))
        total_earnings = sum(lines.mapped('seller_amount'))

        # Products assigned by admin
        products = request.env['product.template'].sudo().search([
            ('marketplace_seller_id', '=', partner.id),
        ])

        # Recent orders
        SaleOrder = request.env['sale.order'].sudo()
        recent_orders = SaleOrder.search([
            ('marketplace_seller_id', '=', partner.id),
            ('state', 'in', ('sale', 'done')),
        ], order='date_order desc', limit=10)

        values = {
            'partner': partner,
            'total_sales': total_sales,
            'total_commissions': total_commissions,
            'total_earnings': total_earnings,
            'pending_commissions': sum(
                lines.filtered(lambda l: l.state == 'pending').mapped('commission_amount')
            ),
            'product_count': len(products),
            'products': products,
            'order_count': len(recent_orders),
            'recent_orders': recent_orders,
            'active_menu': 'dashboard',
        }
        return request.render('synara-marketplace.seller_dashboard', values)

    # ── Profile ──
    @http.route(
        ['/mi/marketplace/perfil'],
        type='http', auth='user', website=True,
        methods=['GET', 'POST'],
    )
    def seller_profile(self, **post):
        partner, denied = self._ensure_seller()
        if not partner:
            return denied

        flash = request.session.pop('marketplace_profile_flash', False)
        error = request.session.pop('marketplace_profile_error', False)

        IrConfig = request.env['ir.config_parameter'].sudo()
        client_id = IrConfig.get_param('synara_mp.mp_client_id')
        mp_available = bool(client_id)

        if request.httprequest.method == 'POST':
            update_vals = {}
            store_name = (post.get('seller_store_name') or '').strip()
            description = (post.get('seller_description') or '').strip()
            phone = (post.get('phone') or '').strip()

            if store_name:
                update_vals['seller_store_name'] = store_name
            if description is not None:
                update_vals['seller_description'] = description or False
            if phone is not None:
                update_vals['phone'] = phone or False

            logo_file = request.httprequest.files.get('seller_logo')
            if logo_file and logo_file.filename:
                data = logo_file.read()
                update_vals['seller_logo'] = base64.b64encode(data)

            if update_vals:
                partner.sudo().write(update_vals)
                request.session['marketplace_profile_flash'] = 'Perfil actualizado correctamente.'
                return request.redirect('/mi/marketplace/perfil')

        values = {
            'partner': partner,
            'flash': flash,
            'error': error,
            'mp_available': mp_available,
            'connect_url': '/mi/marketplace/mercadopago/conectar' if mp_available else False,
            'active_menu': 'profile',
        }
        return request.render('synara-marketplace.seller_profile', values)

    # ── Orders ──
    @http.route(
        ['/mi/marketplace/pedidos'],
        type='http', auth='user', website=True,
    )
    def seller_orders(self, **kw):
        partner, denied = self._ensure_seller()
        if not partner:
            return denied

        orders = request.env['sale.order'].sudo().search([
            ('marketplace_seller_id', '=', partner.id),
            ('state', 'in', ('sale', 'done')),
        ], order='date_order desc')

        values = {
            'partner': partner,
            'orders': orders,
            'active_menu': 'orders',
        }
        return request.render('synara-marketplace.seller_orders', values)

    @http.route(
        ['/mi/marketplace/pedidos/<int:order_id>'],
        type='http', auth='user', website=True,
    )
    def seller_order_detail(self, order_id, **kw):
        partner, denied = self._ensure_seller()
        if not partner:
            return denied

        order = request.env['sale.order'].sudo().browse(order_id)
        if not order.exists() or order.marketplace_seller_id.id != partner.id:
            return request.redirect('/mi/marketplace/pedidos')

        values = {
            'partner': partner,
            'order': order,
            'active_menu': 'orders',
        }
        return request.render('synara-marketplace.seller_order_detail', values)

    # ── Commissions ──
    @http.route(
        ['/mi/marketplace/comisiones'],
        type='http', auth='user', website=True,
    )
    def seller_commissions(self, **kw):
        partner, denied = self._ensure_seller()
        if not partner:
            return denied

        lines = request.env['marketplace.commission.line'].sudo().search([
            ('seller_id', '=', partner.id),
        ], order='create_date desc')

        values = {
            'partner': partner,
            'commission_lines': lines,
            'active_menu': 'commissions',
        }
        return request.render('synara-marketplace.seller_commissions', values)
