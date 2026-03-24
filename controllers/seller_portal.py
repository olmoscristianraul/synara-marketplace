# -*- coding: utf-8 -*-
import base64
import logging
import csv
import io
import re

from odoo import http, _, fields, _
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
            'pending_deliveries': SaleOrder.search_count([
                ('marketplace_seller_id', '=', partner.id),
                ('state', 'in', ('sale', 'done')),
                ('marketplace_delivery_status', '=', 'pending'),
            ]),
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

        # Counts for sidebar badges
        SaleOrder = request.env['sale.order'].sudo()
        pending_deliveries = SaleOrder.search_count([
            ('marketplace_seller_id', '=', partner.id),
            ('state', 'in', ('sale', 'done')),
            ('marketplace_delivery_status', '=', 'pending'),
        ])
        
        values = {
            'partner': partner,
            'orders': orders,
            'pending_deliveries': pending_deliveries,
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

        flash = request.session.pop('marketplace_order_flash', False)
        
        values = {
            'partner': partner,
            'order': order,
            'flash': flash,
            'active_menu': 'orders',
        }
        return request.render('synara-marketplace.seller_order_detail', values)

    @http.route(
        ['/mi/marketplace/pedidos/<int:order_id>/estado'],
        type='http', auth='user', website=True, methods=['POST']
    )
    def seller_order_update_status(self, order_id, **post):
        partner, denied = self._ensure_seller()
        if not partner: return denied
        
        order = request.env['sale.order'].sudo().browse(order_id)
        if order.exists() and order.marketplace_seller_id.id == partner.id:
            new_status = post.get('status')
            if new_status in ['shipped', 'cancelled', 'invoiced']:
                order.write({'marketplace_delivery_status': new_status})
                status_label = dict(order._fields['marketplace_delivery_status'].selection).get(new_status)
                order.message_post(body=f"El vendedor ha cambiado el estado a: {status_label}")
                
                # Logic for deliveries (same as before)
                if new_status == 'shipped' and hasattr(order, 'picking_ids'):
                    pickings = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
                    for picking in pickings:
                        try:
                            picking.action_assign()
                            for move in picking.move_ids_without_package:
                                move.quantity = move.product_uom_qty
                            picking.button_validate()
                        except Exception as e:
                            _logger.warning('Marketplace Delivery Warning: %s', e)
                
                request.session['marketplace_order_flash'] = f'Pedido actualizado a {status_label}.'
        return request.redirect(f'/mi/marketplace/pedidos/{order_id}')

    @http.route(
        ['/mi/marketplace/pedidos/<int:order_id>/subir_factura'],
        type='http', auth='user', website=True, methods=['POST']
    )
    def seller_order_upload_invoice(self, order_id, **post):
        partner, denied = self._ensure_seller()
        if not partner: return denied
        
        order = request.env['sale.order'].sudo().browse(order_id)
        if order.exists() and order.marketplace_seller_id.id == partner.id:
            invoice_file = request.httprequest.files.get('invoice_file')
            if invoice_file and invoice_file.filename:
                attachment = request.env['ir.attachment'].sudo().create({
                    'name': invoice_file.filename,
                    'type': 'binary',
                    'datas': base64.b64encode(invoice_file.read()),
                    'res_model': 'sale.order',
                    'res_id': order.id,
                })
                # Auto-transition to invoiced if requested or as a standard flow
                order.write({'marketplace_delivery_status': 'invoiced'})
                order.message_post(body="El vendedor adjuntó la factura y marcó el pedido como Facturado.", attachment_ids=[attachment.id])
                request.session['marketplace_order_flash'] = 'Factura subida y pedido marcado como Facturado.'
        return request.redirect(f'/mi/marketplace/pedidos/{order_id}')

    # ── Products CRUD ──
    @http.route(
        ['/mi/marketplace/productos'],
        type='http', auth='user', website=True,
    )
    def seller_products(self, **kw):
        partner, denied = self._ensure_seller()
        if not partner: return denied

        products = request.env['product.template'].sudo().search([
            ('marketplace_seller_id', '=', partner.id),
        ], order='create_date desc')

        # Counts for sidebar badges
        SaleOrder = request.env['sale.order'].sudo()
        pending_deliveries = SaleOrder.search_count([
            ('marketplace_seller_id', '=', partner.id),
            ('state', 'in', ('sale', 'done')),
            ('marketplace_delivery_status', '=', 'pending'),
        ])

        values = {
            'partner': partner,
            'products': products,
            'pending_deliveries': pending_deliveries,
            'flash': request.session.pop('marketplace_product_flash', False),
            'active_menu': 'products',
        }
        return request.render('synara-marketplace.seller_products_list', values)

    @http.route(
        ['/mi/marketplace/productos/nuevo', '/mi/marketplace/productos/editar/<int:product_id>'],
        type='http', auth='user', website=True, methods=['GET', 'POST']
    )
    def seller_product_form(self, product_id=None, **post):
        partner, denied = self._ensure_seller()
        if not partner: return denied

        Product = request.env['product.template'].sudo()
        product = Product.browse(product_id) if product_id else Product

        if product_id and (not product.exists() or product.marketplace_seller_id.id != partner.id):
            return request.redirect('/mi/marketplace/productos')

        if request.httprequest.method == 'POST':
            name = post.get('name')
            list_price = float(post.get('list_price') or 0.0)
            promo_price = float(post.get('promo_price') or 0.0)
            shipping_cost = float(post.get('shipping_cost') or 0.0)
            stock_qty = float(post.get('stock_qty') or 0.0)
            description_sale = post.get('description_sale') or ''
            
            vals = {
                'name': name,
                'list_price': list_price,
                'marketplace_promo_price': promo_price,
                'marketplace_shipping_cost': shipping_cost,
                'description_sale': description_sale,
                'detailed_type': 'product',
                'marketplace_seller_id': partner.id,
                'website_published': False if not product_id else product.website_published,
            }
            if not product_id:
                vals['marketplace_approved'] = False
            
            image_file = request.httprequest.files.get('image_1920')
            if image_file and image_file.filename:
                vals['image_1920'] = base64.b64encode(image_file.read())

            if product_id:
                product.write(vals)
                msg = 'Producto actualizado.'
            else:
                product = Product.create(vals)
                msg = 'Producto creado. Pendiente de aprobación por admin.'

            # Actualizar stock
            if 'stock_qty' in post:
                try:
                    warehouse = request.env['stock.warehouse'].sudo().search([('company_id', '=', product.company_id.id)], limit=1)
                    if warehouse:
                        location = warehouse.lot_stock_id
                        quant = request.env['stock.quant'].sudo().with_context(inventory_mode=True).create({
                            'product_id': product.product_variant_id.id,
                            'location_id': location.id,
                            'inventory_quantity': stock_qty,
                        })
                        quant.action_apply_inventory()
                except Exception as e:
                    _logger.warning('Failed to update stock: %s', e)

            request.session['marketplace_product_flash'] = msg
            return request.redirect('/mi/marketplace/productos')

        current_stock = product.qty_available if product_id and hasattr(product, 'qty_available') else 0.0

        values = {
            'partner': partner,
            'product': product,
            'current_stock': current_stock,
            'active_menu': 'products',
        }
        return request.render('synara-marketplace.seller_product_form', values)

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

    # ── Bulk Management ──
    @http.route(
        ['/mi/marketplace/productos/importar'],
        type='http', auth='user', website=True,
        methods=['GET', 'POST'],
    )
    def seller_products_import(self, **post):
        partner, denied = self._ensure_seller()
        if not partner:
            return denied

        if request.httprequest.method == 'POST' and post.get('csv_file'):
            csv_file = post.get('csv_file')
            try:
                content = csv_file.read().decode('utf-8')
                stream = io.StringIO(content)
                reader = csv.DictReader(stream)
                
                created, updated, errors = 0, 0, []
                ProductTemplate = request.env['product.template'].sudo()
                
                for row in reader:
                    try:
                        ref = row.get('referencia_interna', '').strip()
                        name = row.get('nombre', '').strip()
                        if not name and not ref:
                            continue
                            
                        vals = {
                            'name': name or ref,
                            'list_price': float(row.get('precio', 0.0) or 0.0),
                            'marketplace_promo_price': float(row.get('precio_oferta', 0.0) or 0.0),
                            'marketplace_shipping_cost': float(row.get('envio', 0.0) or 0.0),
                            'description_sale': row.get('descripcion', ''),
                            'marketplace_seller_id': partner.id,
                            'detailed_type': 'product',
                            'marketplace_commission_percent': partner.seller_commission_percent,
                        }
                        
                        product = False
                        if ref:
                            product = ProductTemplate.search([
                                ('default_code', '=', ref),
                                ('marketplace_seller_id', '=', partner.id)
                            ], limit=1)
                        
                        if product:
                            product.write(vals)
                            updated += 1
                        else:
                            vals['default_code'] = ref
                            vals['website_published'] = False
                            ProductTemplate.create(vals)
                            created += 1
                            
                    except Exception as e:
                        errors.append(f"Error en fila {name or ref}: {str(e)}")
                
                msg = f"Importación finalizada: {created} creados, {updated} actualizados."
                if errors:
                    msg += f" Errores: {len(errors)}"
                request.session['marketplace_product_flash'] = msg
                return request.redirect('/mi/marketplace/productos')
            except Exception as e:
                _logger.error("CSV Import error: %s", e)
                request.session['marketplace_product_flash'] = f"Error al procesar el archivo: {str(e)}"

        return request.render('synara-marketplace.seller_products_import', {
            'partner': partner,
            'active_menu': 'products',
        })

    @http.route('/mi/marketplace/productos/plantilla_csv', type='http', auth='user')
    def seller_products_template(self):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['referencia_interna', 'nombre', 'precio', 'precio_oferta', 'envio', 'descripcion'])
        writer.writerow(['REF001', 'Producto de ejemplo', '1500.00', '1200.00', '350.00', 'Descripción del producto'])
        
        csv_content = output.getvalue()
        return request.make_response(csv_content, [
            ('Content-Type', 'text/csv'),
            ('Content-Disposition', 'attachment; filename=plantilla_productos.csv;')
        ])
