import logging

from odoo import http
from odoo.http import request

from .portal_base import PhotographerPortalMixin

_logger = logging.getLogger(__name__)


class PhotographerDebtController(PhotographerPortalMixin, http.Controller):

    @http.route(['/mi/fotoapp/deudas'], type='http', auth='user', website=True)
    def photographer_debts(self, **kwargs):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied

        Debt = request.env['fotoapp.debt'].sudo()
        partner_ids = {partner.id}
        if partner.commercial_partner_id:
            partner_ids.add(partner.commercial_partner_id.id)
        domain = [('partner_id', 'in', list(partner_ids))]
        active_debts = Debt.search(domain + [('state', 'in', ['pending', 'in_grace'])],
                                   order='due_date asc')
        paid_debts = Debt.search(domain + [('state', '=', 'paid')], order='paid_date desc', limit=50)
        values = {
            'partner': partner,
            'active_debts': active_debts,
            'paid_debts': paid_debts,
            'active_menu': 'debts',
        }
        return request.render('fotoapp.photographer_debts_page', values)

    @http.route(['/mi/fotoapp/deuda/<int:debt_id>/carrito'], type='http', auth='user', website=True)
    def add_debt_to_cart(self, debt_id, **kwargs):
        partner, denied = self._ensure_photographer()
        if not partner:
            return denied

        Debt = request.env['fotoapp.debt'].sudo()
        debt = Debt.browse(debt_id)
        if not debt or debt.partner_id != partner or not debt.can_be_paid():
            return request.not_found()

        if debt.sale_order_id and debt.sale_order_id.state in ('draft', 'sent'):
            order = debt.sale_order_id
        else:
            order = request.website.sale_get_order(force_create=1)
        if not order:
            return request.redirect('/shop/cart')

        # Ensure order is bound to the photographer partner and website/pricelist so the cart can display it
        order_vals = {}
        if not order.partner_id:
            order_vals.update({
                'partner_id': partner.id,
                'partner_invoice_id': partner.id,
                'partner_shipping_id': partner.id,
            })
        if not order.website_id:
            order_vals['website_id'] = request.website.id
        if not order.pricelist_id and request.website.get_current_pricelist():
            order_vals['pricelist_id'] = request.website.get_current_pricelist().id
        if order_vals:
            order.sudo().write(order_vals)

        # Ensure the cart session points to the order we are using
        request.session['sale_order_id'] = order.id
        if order.pricelist_id:
            request.session['website_sale_current_pl'] = order.pricelist_id.id

        product_variant = self._get_debt_product_variant()
        if not product_variant:
            _logger.error('No se pudo encontrar el producto de renovación para registrar la deuda.')
            return request.redirect('/shop/cart')

        # Eliminamos la línea previa si existe para mantener un único item por deuda
        if debt.sale_order_line_id and debt.sale_order_line_id.order_id == order:
            debt.sale_order_line_id.unlink()

        line_vals = {
            'order_id': order.id,
            'product_id': product_variant.id,
            'name': '%s - %s' % (debt.get_portal_label(), debt.plan_id.name or ''),
            'product_uom_qty': 1,
            'price_unit': debt.amount,
        }
        line = request.env['sale.order.line'].sudo().create(line_vals)
        debt.write({
            'sale_order_id': order.id,
            'sale_order_line_id': line.id,
        })
        _logger.info('FotoApp debt added to cart: debt_id=%s order_id=%s line_id=%s user=%s', debt.id, order.id, line.id, request.env.user.id)
        return request.redirect('/shop/cart')

    def _get_debt_product_variant(self):
        # Fetch product template with sudo to avoid portal read restrictions
        imd = request.env['ir.model.data'].sudo()
        ProductTemplate = request.env['product.template'].sudo()
        template = False

        xmlid_rec = imd.search([('module', '=', 'fotoapp'), ('name', '=', 'product_plan_renewal_template')], limit=1)
        if xmlid_rec:
            model = xmlid_rec.model
            res_id = xmlid_rec.res_id
            template = request.env[model].sudo().browse(res_id) if model else False
        else:
            try:
                _, _, model, res_id = imd._xmlid_lookup('fotoapp.product_plan_renewal_template')
                template = request.env[model].sudo().browse(res_id)
            except ValueError:
                template = False

        if not template or not template.exists():
            # Create or recreate the renewal template if missing, and bind xmlid without duplicating
            template_vals = {
                'name': 'Renovación plan Fotógrafo',
                'list_price': 0.0,
                'invoice_policy': 'order',
                'sale_ok': True,
                'purchase_ok': False,
                'taxes_id': [(5, 0, 0)],
                'company_id': False,
                'website_published': True,
                'description_sale': 'Renovación mensual del plan de fotógrafo',
            }
            if 'detailed_type' in ProductTemplate._fields:
                template_vals['detailed_type'] = 'service'
            elif 'type' in ProductTemplate._fields:
                template_vals['type'] = 'service'
            template = ProductTemplate.create(template_vals)

            if xmlid_rec:
                xmlid_rec.sudo().write({'model': 'product.template', 'res_id': template.id})
            else:
                imd.create({
                    'name': 'product_plan_renewal_template',
                    'module': 'fotoapp',
                    'model': 'product.template',
                    'res_id': template.id,
                    'noupdate': True,
                })

        # Ensure the renewal product is visible and sellable on website for portal users
        publish_vals = {}
        if 'website_published' in template._fields and not template.website_published:
            publish_vals['website_published'] = True
        if 'sale_ok' in template._fields and not template.sale_ok:
            publish_vals['sale_ok'] = True
        if publish_vals:
            template.write(publish_vals)

        if template.product_variant_id:
            return template.product_variant_id.sudo()

        return request.env['product.product'].sudo().search([('product_tmpl_id', '=', template.id)], limit=1)
