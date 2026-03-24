import base64
import hashlib
import logging
import secrets
from datetime import timedelta
from io import BytesIO

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from PIL import Image, ImageDraw, ImageFont

_logger = logging.getLogger(__name__)


class TiendaFotoAsset(models.Model):
    _name = 'tienda.foto.asset'
    _description = 'Activos de fotos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id desc'

    evento_id = fields.Many2one(
        comodel_name='tienda.foto.evento',
        string='Evento',
        required=True,
        ondelete='cascade'
    )
    photographer_id = fields.Many2one(
        'res.partner',
        string='Fotógrafo',
        related='evento_id.photographer_id',
        store=True,
        readonly=True
    )
    plan_subscription_id = fields.Many2one(
        comodel_name='sale.subscription',
        related='evento_id.plan_subscription_id',
        store=True,
        string='Suscripción'
    )
    numero_dorsal = fields.Char(string='Número de Dorsal', copy=False, readonly=True)
    name = fields.Char(string='Nombre', default=lambda self: _('Foto sin nombre'))
    sequence = fields.Integer(string='Secuencia', default=10)
    imagen_original = fields.Image(string='Imagen Original', required=True, attachment=True)
    imagen_watermark = fields.Image(string='Imagen con Marca de Agua', attachment=True)
    precio = fields.Monetary(string='Precio', currency_field='currency_id', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id.id)
    publicada = fields.Boolean(string='Publicada', default=True)
    website_published = fields.Boolean(string='Visible en web', default=True)
    checksum = fields.Char(string='Checksum', readonly=True)
    download_token = fields.Char(string='Token de descarga')
    batch_id = fields.Char(string='Lote de subida')
    album_ids = fields.Many2many(
        comodel_name='tienda.foto.album',
        relation='tienda_foto_album_asset_rel',
        column1='asset_id',
        column2='album_id',
        string='Álbumes'
    )
    lifecycle_state = fields.Selection([
        ('draft', 'Borrador'),
        ('pending_review', 'Pendiente de revisión'),
        ('ready_for_sale', 'Lista para vender'),
        ('published', 'Publicada'),
        ('sold', 'Vendida'),
        ('delivered', 'Entregada'),
        ('archived', 'Archivada')
    ], string='Estado', default='published', tracking=True)
    publicada_por_ultima_vez = fields.Datetime(string='Publicada por última vez', copy=False, default=lambda self: fields.Datetime.now())
    archived_at = fields.Datetime(string='Archivada el', copy=False)
    days_until_archive = fields.Integer(string='Días hasta archivado', compute='_compute_lifecycle_deadlines')
    days_until_delete = fields.Integer(string='Días hasta eliminación', compute='_compute_lifecycle_deadlines')
    portal_token = fields.Char(string='Token portal', copy=False)
    portal_url = fields.Char(string='URL portal', compute='_compute_portal_url')
    sale_order_line_ids = fields.One2many('sale.order.line', 'foto_asset_id', string='Líneas de venta')
    product_id = fields.Many2one('product.product', string='Producto ecommerce', copy=False, readonly=True)
    sale_count = fields.Integer(string='Ventas totales', compute='_compute_sales_metrics', store=True)
    sale_total_amount = fields.Monetary(string='Ventas acumuladas', currency_field='currency_id', compute='_compute_sales_metrics', store=True)
    last_sale_date = fields.Datetime(string='Última venta', compute='_compute_sales_metrics', store=True)
    statement_line_ids = fields.One2many('fotoapp.photographer.statement.line', 'asset_id', string='Liquidaciones')
    file_size_bytes = fields.Integer(string='Tamaño de archivo', readonly=True)
    digital_download_url = fields.Char(string='URL descarga directa')
    download_limit = fields.Integer(string='Descargas permitidas', default=0, help='0 significa ilimitado.')
    download_count = fields.Integer(string='Descargas realizadas', default=0)
    last_download_date = fields.Datetime(string='Última descarga')
    _sql_constraints = [
        ('foto_portal_token_unique', 'unique(portal_token)', 'El token de la foto debe ser único.'),
        ('foto_unique_dorsal_photographer', 'unique(photographer_id, numero_dorsal)', 'Ya existe una foto con ese identificador para este fotógrafo.'),
    ]

    def _compute_checksum(self, b64_image): 
        # Sirve para detectar duplicados o verificar integridad.
        # Convierte el binario base64 a bytes, calcula hashlib.sha256, guarda el resultado en el campo checksum.
        if not b64_image: #si viene vacío
            return False
        raw = base64.b64decode(b64_image)
        return hashlib.sha256(raw).hexdigest()

    def _compute_file_size(self, b64_image):
        if not b64_image:
            return 0
        try:
            return len(base64.b64decode(b64_image))
        except Exception:
            return 0
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            photographer_id = self._resolve_photographer(vals)
            if not photographer_id:
                raise ValidationError(_('Cada foto debe pertenecer a un fotógrafo para asignar un identificador.'))
            vals['numero_dorsal'] = self._next_numero_dorsal(photographer_id)
            if not vals.get('name'):
                vals['name'] = self._default_name_from_vals(vals)
            subscription = self._resolve_plan_subscription(vals, photographer_id)
            image_b64 = vals.get('imagen_original')
            if not image_b64:
                continue
            size_bytes = self._compute_file_size(image_b64)
            if size_bytes:
                vals['file_size_bytes'] = size_bytes
            if subscription and size_bytes and not subscription.can_store_bytes(size_bytes):
                limit_mb = subscription.plan_id.storage_limit_mb or int((subscription.plan_id.storage_limit_gb or 0.0) * 1024)
                raise ValidationError(_('Alcanzaste el límite de almacenamiento de tu plan (%s MB).') % limit_mb)
            checksum = self._compute_checksum(image_b64)
            if checksum:
                vals['checksum'] = checksum
            vals.setdefault('publicada_por_ultima_vez', fields.Datetime.now())
            vals.setdefault('portal_token', self._generate_portal_token())
            vals.setdefault('publicada', True)
            vals.setdefault('website_published', True)
            vals.setdefault('lifecycle_state', 'published')
            self._generate_watermark(vals)
        return super().create(vals_list)

    def _default_name_from_vals(self, vals):
        dorsal = vals.get('numero_dorsal')
        if dorsal:
            return _('Foto %s') % dorsal
        return _('Foto sin nombre')

    def _resolve_photographer(self, vals):
        photographer_id = vals.get('photographer_id')
        if photographer_id:
            return photographer_id
        event_id = vals.get('evento_id')
        if not event_id:
            return False
        event = self.env['tienda.foto.evento'].browse(event_id)
        return event.photographer_id.id if event else False

    def _resolve_plan_subscription(self, vals, photographer_id):
        if vals.get('plan_subscription_id'):
            return self.env['sale.subscription'].browse(vals['plan_subscription_id'])
        event_id = vals.get('evento_id')
        if event_id:
            event = self.env['tienda.foto.evento'].browse(event_id)
            if event and event.plan_subscription_id:
                return event.plan_subscription_id
        partner = self.env['res.partner'].browse(photographer_id)
        return partner.active_plan_subscription_id

    def _next_numero_dorsal(self, photographer_id):
        self.env.cr.execute(
            """
            SELECT COALESCE(fotoapp_next_photo_identifier, 0)
            FROM res_partner
            WHERE id = %s
            FOR UPDATE
            """,
            (photographer_id,)
        )
        row = self.env.cr.fetchone()
        if row is None:
            raise ValidationError(_('No se encontró el fotógrafo para generar el identificador de la foto.'))
        next_value = (row[0] or 0) + 1
        self.env.cr.execute(
            """
            UPDATE res_partner
            SET fotoapp_next_photo_identifier = %s
            WHERE id = %s
            """,
            (next_value, photographer_id)
        )
        return str(next_value)
    
    def _generate_watermark(self, vals):
        image_b64 = vals.get('imagen_original')
        if not image_b64:
            return vals
        try:
            raw = base64.b64decode(image_b64)
            image = Image.open(BytesIO(raw)).convert("RGBA") #abre la imagen y la convierte apra poder trabajarla.
        except Exception as exc:
            _logger.warning("No se pudo generar la marca de agua: %s", exc)
            return vals
    
        watermark = Image.new("RGBA", image.size)
        overlay_added = self._apply_partner_watermark(image, watermark, vals)
        if not overlay_added:
            draw = ImageDraw.Draw(watermark)
            try:
                font = ImageFont.truetype("arial.ttf", 48)
            except OSError:
                font = ImageFont.load_default()
            draw.text((30, 30), "FotoApp", fill=(255, 255, 255, 128), font=font)

        combined = Image.alpha_composite(image, watermark)
        buf = BytesIO() #crea un buffer en memoria para guardar la imagen resultante
        combined.convert("RGB").save(buf, format="JPEG", quality=85)
        vals['imagen_watermark'] = base64.b64encode(buf.getvalue())
        return vals

    def _apply_partner_watermark(self, base_image, watermark_layer, vals):
        partner = self._get_photographer(vals)
        if not partner or not partner.watermark_image:
            return False
        try:
            partner_img = Image.open(BytesIO(base64.b64decode(partner.watermark_image))).convert("RGBA")
        except Exception as exc:
            _logger.warning('Marca de agua inválida para %s: %s', partner.name, exc)
            return False

        scale = min(max(partner.watermark_scale or 0.3, 0.05), 1.0)
        opacity = min(max(partner.watermark_opacity or 60, 0), 100) / 100.0
        target_width = max(int(base_image.width * scale), 1)
        ratio = target_width / float(partner_img.width)
        target_height = max(int(partner_img.height * ratio), 1)
        partner_img = partner_img.resize((target_width, target_height), Image.LANCZOS)

        if partner_img.mode != 'RGBA':
            partner_img = partner_img.convert('RGBA')
        alpha = partner_img.split()[3].point(lambda p: int(p * opacity))
        partner_img.putalpha(alpha)

        position = (
            max(int((base_image.width - partner_img.width) / 2), 0),
            max(int((base_image.height - partner_img.height) / 2), 0)
        )
        watermark_layer.alpha_composite(partner_img, dest=position)
        return True

    def _get_photographer(self, vals):
        if vals.get('photographer_id'):
            return self.env['res.partner'].browse(vals['photographer_id'])
        event_id = vals.get('evento_id')
        if not event_id:
            return None
        event = self.env['tienda.foto.evento'].browse(event_id)
        return event.photographer_id
    
    def write(self, vals):
        previous_states = {}
        if 'lifecycle_state' in vals and not self.env.context.get('skip_lifecycle_side_effects'):
            previous_states = {asset.id: asset.lifecycle_state for asset in self}
        if 'imagen_original' in vals:
            vals = self._generate_watermark(vals)
            size_bytes = self._compute_file_size(vals['imagen_original'])
            if size_bytes:
                vals['file_size_bytes'] = size_bytes
            checksum = self._compute_checksum(vals['imagen_original'])
            if checksum:
                vals['checksum'] = checksum
        if vals.get('portal_token') is False:
            vals['portal_token'] = self._generate_portal_token()
        res = super().write(vals)
        if previous_states:
            for asset in self:
                old_state = previous_states.get(asset.id)
                new_state = asset.lifecycle_state
                if new_state == 'published' and old_state != 'published':
                    asset._on_published()
                if new_state == 'archived' and old_state != 'archived':
                    asset._on_archived()
        if any(key in vals for key in ['precio', 'name']):
            self._sync_sale_products()
        return res

    def regenerate_watermark(self):
        for asset in self:
            if not asset.imagen_original:
                continue
            vals = {
                'imagen_original': asset.imagen_original,
                'photographer_id': asset.photographer_id.id,
                'evento_id': asset.evento_id.id,
            }
            self._generate_watermark(vals)
            if vals.get('imagen_watermark'):
                asset.imagen_watermark = vals['imagen_watermark']

    def ensure_download_token(self):
        for asset in self:
            if not asset.download_token:
                token = asset._generate_portal_token()
                asset.sudo().write({'download_token': token})
        return {asset.id: asset.download_token for asset in self}

    def ensure_sale_product(self):
        for asset in self:
            asset = asset.sudo()
            product = asset.product_id
            if not product or not product.exists():
                product = asset._create_sale_product()
                asset.product_id = product.id
            else:
                asset._sync_sale_product_values(product)
        return self.mapped('product_id')

    def _create_sale_product(self):
        self.ensure_one()
        Product = self.env['product.product'].sudo()
        vals = self._prepare_sale_product_vals()
        return Product.create(vals)

    def _prepare_sale_product_vals(self):
        self.ensure_one()
        categ = self.env.ref('product.product_category_all', raise_if_not_found=False)
        description = self._get_sale_description()
        return {
            'name': self.name or _('Foto %s') % (self.numero_dorsal or self.id),
            'sale_ok': True,
            'purchase_ok': False,
            'type': 'service',
            'list_price': self.precio,
            'standard_price': 0.0,
            'taxes_id': [(6, 0, [])],
            'categ_id': categ.id if categ else False,
            'website_published': True,
            'description_sale': description,
        }

    def _get_sale_description(self):
        self.ensure_one()
        event_name = self.evento_id.name or ''
        photographer = self.photographer_id.name or ''
        return _('%s · Evento %s · Fotógrafo %s') % (
            self.name or _('Foto %s') % (self.numero_dorsal or self.id),
            event_name,
            photographer,
        )

    def _sync_sale_products(self):
        for asset in self.filtered('product_id'):
            asset._sync_sale_product_values(asset.product_id)

    def _sync_sale_product_values(self, product):
        self.ensure_one()
        product_vals = {
            'name': self.name or product.name,
            'list_price': self.precio,
            'sale_ok': True,
        }
        product.sudo().write(product_vals)
        product.product_tmpl_id.sudo().write({
            'website_published': True,
            'description_sale': self._get_sale_description(),
        })

    @api.constrains('precio')
    def _check_precio(self):
        for record in self:
            if record.precio <= 0:
                raise ValidationError(_('El precio debe ser mayor a cero.'))

    @api.depends('sale_order_line_ids.price_total', 'sale_order_line_ids.order_id.date_order')
    def _compute_sales_metrics(self):
        for asset in self:
            asset.sale_count = len(asset.sale_order_line_ids)
            asset.sale_total_amount = sum(asset.sale_order_line_ids.mapped('price_total'))
            dates = []
            for line in asset.sale_order_line_ids:
                order = line.order_id
                order_date = getattr(order, 'confirmation_date', False) or order.date_order
                if order_date:
                    dates.append(order_date)
            asset.last_sale_date = max(dates) if dates else False

    @api.depends('portal_token')
    def _compute_portal_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for asset in self:
            asset.portal_url = f"{base_url}/fotoapp/photo/{asset.portal_token}" if asset.portal_token else False

    def _generate_portal_token(self):
        return secrets.token_urlsafe(16)

    def action_publish(self):
        self.write({'lifecycle_state': 'published', 'publicada': True, 'website_published': True})

    def action_archive(self):
        self.write({'lifecycle_state': 'archived', 'publicada': False, 'website_published': False})

    def _on_published(self):
        now = fields.Datetime.now()
        values = {
            'publicada_por_ultima_vez': now,
            'archived_at': False,
            'publicada': True,
            'website_published': True,
        }
        self.with_context(skip_lifecycle_side_effects=True).write(values)

    def _on_archived(self):
        now = fields.Datetime.now()
        values = {
            'archived_at': now,
            'publicada': False,
            'website_published': False,
        }
        self.with_context(skip_lifecycle_side_effects=True).write(values)

    def _bump_publication_clock(self):
        now = fields.Datetime.now()
        self.with_context(skip_lifecycle_side_effects=True).write({'publicada_por_ultima_vez': now})

    def _lifecycle_anchor_date(self):
        self.ensure_one()
        anchor = self.publicada_por_ultima_vez or self.create_date
        if self.last_sale_date and (not anchor or self.last_sale_date > anchor):
            anchor = self.last_sale_date
        return anchor

    @api.model
    def _get_lifecycle_config(self):
        icp = self.env['ir.config_parameter'].sudo()
        archive_days = self._safe_int_param(icp, 'fotoapp.asset_archive_days', 30)
        delete_days = self._safe_int_param(icp, 'fotoapp.asset_delete_days', 15)
        return archive_days, delete_days

    @staticmethod
    def _safe_int_param(config, key, default):
        try:
            raw_value = config.get_param(key)
            return int(raw_value) if raw_value is not None else int(default)
        except (TypeError, ValueError):
            return int(default)

    def _get_archive_deadline(self, archive_days):
        self.ensure_one()
        base_date = self._lifecycle_anchor_date()
        if not archive_days or not base_date:
            return False
        return base_date + timedelta(days=archive_days)

    def _get_delete_deadline(self, delete_days):
        self.ensure_one()
        base_date = self.archived_at or self.write_date or self.create_date
        if not delete_days or not base_date:
            return False
        return base_date + timedelta(days=delete_days)

    @api.depends('publicada_por_ultima_vez', 'archived_at', 'lifecycle_state', 'last_sale_date')
    def _compute_lifecycle_deadlines(self):
        archive_days, delete_days = self._get_lifecycle_config()
        now = fields.Datetime.now()
        for asset in self:
            days_to_archive = False
            days_to_delete = False
            if asset.lifecycle_state == 'published':
                deadline = asset._get_archive_deadline(archive_days)
                if deadline:
                    days_to_archive = max((deadline - now).days, 0)
            if asset.lifecycle_state == 'archived':
                deadline = asset._get_delete_deadline(delete_days)
                if deadline:
                    days_to_delete = max((deadline - now).days, 0)
            asset.days_until_archive = days_to_archive
            asset.days_until_delete = days_to_delete

    @api.model
    def cron_manage_photo_lifecycle(self):
        archive_days, delete_days = self._get_lifecycle_config()
        now = fields.Datetime.now()

        published_assets = self.search([('lifecycle_state', '=', 'published')])
        to_archive = self.browse()
        for asset in published_assets:
            deadline = asset._get_archive_deadline(archive_days)
            if deadline and deadline <= now:
                to_archive |= asset
        if to_archive:
            to_archive.action_archive()

        archived_assets = self.search([('lifecycle_state', '=', 'archived')])
        to_delete = self.browse()
        for asset in archived_assets:
            deadline = asset._get_delete_deadline(delete_days)
            if deadline and deadline <= now:
                to_delete |= asset
        if to_delete:
            to_delete.unlink()
    

