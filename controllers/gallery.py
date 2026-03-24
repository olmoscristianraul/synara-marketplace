import logging

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class FotoappGalleryController(http.Controller):
    def _category_domain(self):
        return [
            ('website_published', '=', True),
            ('estado', '!=', 'archivado'),
        ]

    def _get_categories(self, limit=None, require_events=False, order_by_popularity=False):
        domain = list(self._category_domain())
        if require_events:
            domain.append(('website_event_count', '>', 0))
        order = 'sequence, name'
        if order_by_popularity:
            order = 'website_event_count desc, sequence, name'
        return request.env['tienda.foto.categoria'].sudo().search(domain, order=order, limit=limit)

    def _get_public_albums(self, event):
        return request.env['tienda.foto.album'].sudo().search([
            ('event_id', '=', event.id),
            ('state', '=', 'published'),
            ('is_private', '=', False),
        ], order='create_date desc')

    @http.route(['/galeria'], type='http', auth='public', website=True)
    def gallery_home(self, **kwargs):
        top_categories = self._get_categories(limit=6, order_by_popularity=True)
        total_categories = request.env['tienda.foto.categoria'].sudo().search_count(self._category_domain())
        featured_events = request.env['tienda.foto.evento'].sudo().search([
            ('website_published', '=', True),
            ('estado', '=', 'publicado'),
            ('is_featured', '=', True),
        ], limit=6, order='fecha desc')
        recent_events = request.env['tienda.foto.evento'].sudo().search([
            ('website_published', '=', True),
            ('estado', '=', 'publicado'),
        ], limit=8, order='published_at desc, fecha desc')
        values = {
            'categories': top_categories,
            'total_categories': total_categories,
            'category_display_limit': 8,
            'category_more_url': '/galeria/categorias',
            'featured_events': featured_events,
            'recent_events': recent_events,
        }
        return request.render('fotoapp.gallery_categories', values)

    @http.route(['/galeria/categorias'], type='http', auth='public', website=True)
    def gallery_category_listing(self, **kwargs):
        categories = self._get_categories(order_by_popularity=True)
        values = {
            'categories': categories,
            'total_categories': len(categories),
            'breadcrumb': [
                {'label': 'Galería', 'url': '/galeria'},
                {'label': 'Categorías', 'url': False},
            ],
        }
        return request.render('fotoapp.gallery_category_list', values)

    @http.route(['/galeria/categoria/<string:slug>'], type='http', auth='public', website=True)
    def gallery_category(self, slug, **kwargs):
        category = request.env['tienda.foto.categoria'].sudo().search([
            ('slug', '=', slug),
            ('website_published', '=', True),
        ], limit=1)
        if not category:
            return request.not_found()
        events = request.env['tienda.foto.evento'].sudo().search([
            ('categoria_id', '=', category.id),
            ('website_published', '=', True),
            ('estado', '=', 'publicado'),
        ], order='fecha desc')
        values = {
            'category': category,
            'events': events,
            'breadcrumb': [
                {'label': 'Galería', 'url': '/galeria'},
            ],
        }
        return request.render('fotoapp.gallery_category_detail', values)

    @http.route(['/galeria/evento/<string:slug>'], type='http', auth='public', website=True)
    def gallery_event(self, slug, **kwargs):
        event = request.env['tienda.foto.evento'].sudo().search([
            ('website_slug', '=', slug),
            ('website_published', '=', True),
        ], limit=1)
        if not event:
            return request.not_found()
        albums = self._get_public_albums(event)
        values = {
            'event': event,
            'albums': albums,
            'breadcrumb': [
                {'label': 'Galería', 'url': '/galeria'},
                {'label': event.categoria_id.name, 'url': f"/galeria/categoria/{event.categoria_id.slug}"},
            ],
        }
        return request.render('fotoapp.gallery_event_detail', values)

    @http.route(['/galeria/evento/<string:event_slug>/album/<int:album_id>'], type='http', auth='public', website=True)
    def gallery_album(self, event_slug, album_id, **kwargs):
        event = request.env['tienda.foto.evento'].sudo().search([
            ('website_slug', '=', event_slug),
            ('website_published', '=', True),
        ], limit=1)
        if not event:
            return request.not_found()
        album = request.env['tienda.foto.album'].sudo().search([
            ('id', '=', album_id),
            ('event_id', '=', event.id),
            ('state', '=', 'published'),
            ('is_private', '=', False),
        ], limit=1)
        if not album:
            return request.not_found()
        photos = request.env['tienda.foto.asset'].sudo().search([
            ('album_ids', 'in', album.id),
            ('website_published', '=', True),
            ('lifecycle_state', '!=', 'archived'),
        ], order='id desc')
        values = {
            'event': event,
            'album': album,
            'photos': photos,
            'breadcrumb': [
                {'label': 'Galería', 'url': '/galeria'},
                {'label': event.categoria_id.name, 'url': f"/galeria/categoria/{event.categoria_id.slug}"},
                {'label': event.name, 'url': f"/galeria/evento/{event.website_slug}"},
            ],
        }
        return request.render('fotoapp.gallery_album_detail', values)

    @http.route(['/galeria/foto/<int:photo_id>/cart/add'], type='http', auth='public', website=True, methods=['POST'])
    def gallery_add_photo_to_cart(self, photo_id, **post):
        quantity = 1
        try:
            quantity = max(1, int(post.get('quantity', 1)))
        except (TypeError, ValueError):
            quantity = 1
        photo = request.env['tienda.foto.asset'].sudo().search([
            ('id', '=', photo_id),
            ('website_published', '=', True),
            ('lifecycle_state', '!=', 'archived'),
        ], limit=1)
        referer = post.get('redirect') or request.httprequest.referrer or '/galeria'
        if not photo:
            request.session['website_sale_cart_warning'] = _('La foto seleccionada no está disponible.')
            return request.redirect(referer)
        product = photo.ensure_sale_product()[:1]
        if not product:
            request.session['website_sale_cart_warning'] = _('No se pudo preparar la foto para la venta. Intentalo nuevamente en unos instantes.')
            return request.redirect(referer)
        order = request.website.sale_get_order(force_create=True)
        if order:
            order_sudo = order.sudo()
            photo_lines = order_sudo.order_line.filtered(lambda line: line.foto_asset_id)
            existing_photographers = photo_lines.mapped('foto_photographer_id')
            allowed_photographer = existing_photographers[:1]
            if allowed_photographer and allowed_photographer != photo.photographer_id:
                request.session['website_sale_cart_warning'] = _(
                    'El carrito ya contiene fotos de otro fotógrafo. Finalizá esa compra o vacía el carrito '
                    'antes de agregar nuevas fotos.'
                )
                return request.redirect(referer)
        result = order._cart_update(product_id=product.id, add_qty=quantity, set_qty=False)
        line_id = result.get('line_id')
        if line_id:
            line = request.env['sale.order.line'].sudo().browse(line_id)
            line.write({'foto_asset_id': photo.id})
            if order and photo.photographer_id:
                order_sudo = order.sudo()
                order_sudo._apply_photographer_metadata(
                    photo.photographer_id.active_plan_subscription_id,
                    photographer=photo.photographer_id,
                )
                order_sudo._recompute_fotoapp_commission()
        request.session['website_sale_cart_success'] = _('Agregaste %s al carrito.') % (photo.name or _('Foto'))
        return request.redirect(referer)
