# -*- coding: utf-8 -*-
import secrets # sirven para generar tokens únicos y seguros, por ejemplo, para el acceso al portal de un álbum.

from odoo import api, fields, models, _


class TiendaFotoAlbum(models.Model):
    _name = 'tienda.foto.album'
    _description = 'Álbumes y colecciones de fotos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'event_id desc, create_date desc'

    name = fields.Char(string='Nombre del álbum', required=True)
    sequence = fields.Integer(default=10)
    event_id = fields.Many2one('tienda.foto.evento', string='Evento', required=True, ondelete='cascade')
    plan_subscription_id = fields.Many2one('sale.subscription', string='Suscripción', related='event_id.plan_subscription_id', store=True, readonly=True)
    photographer_id = fields.Many2one('res.partner', string='Fotógrafo', related='event_id.photographer_id', store=True, readonly=True)
    partner_id = fields.Many2one('res.partner', string='Cliente asociado')
    customer_email = fields.Char(string='Email del cliente')
    customer_token = fields.Char(string='Token portal', copy=False)
    portal_url = fields.Char(string='URL portal', compute='_compute_portal_url')
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('editing', 'En edición'),
        ('proofing', 'En revisión'),
        ('published', 'Publicado'),
        ('delivered', 'Entregado'),
        ('archived', 'Archivado'),
    ], string='Estado', default='draft', tracking=True)
    expiration_date = fields.Date(string='Fecha de expiración')
    asset_ids = fields.Many2many(
        comodel_name='tienda.foto.asset',
        relation='tienda_foto_album_asset_rel',
        column1='album_id',
        column2='asset_id',
        string='Fotos'
    )
    asset_count = fields.Integer(string='Total de fotos', compute='_compute_asset_count')
    featured_asset_id = fields.Many2one('tienda.foto.asset', string='Foto destacada')
    download_limit = fields.Integer(string='Descargas permitidas', default=0, help='0 significa ilimitado.')
    download_count = fields.Integer(string='Descargas realizadas', default=0)
    last_download_date = fields.Datetime(string='Última descarga')
    download_bundle_url = fields.Char(string='ZIP generado')
    sale_order_id = fields.Many2one('sale.order', string='Pedido asociado')
    is_private = fields.Boolean(string='Privado', default=True)
    allow_guest_checkout = fields.Boolean(string='Permitir compra sin registro', default=True)
    crm_lead_id = fields.Many2one('crm.lead', string='Oportunidad vinculada')
    notes = fields.Text(string='Notas internas')

    _sql_constraints = [
        ('token_unique', 'unique(customer_token)', 'El token del álbum debe ser único.')
    ]

    @api.depends('customer_token')
    def _compute_portal_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for album in self:
            if album.customer_token:
                album.portal_url = f"{base_url}/fotoapp/album/{album.customer_token}"
            else:
                album.portal_url = False

    @api.depends('asset_ids')
    def _compute_asset_count(self):
        for album in self:
            album.asset_count = len(album.asset_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('customer_token'):
                vals['customer_token'] = secrets.token_urlsafe(16)
        return super().create(vals_list)

    def action_publish(self):
        for album in self:
            if album.state in {'draft', 'editing', 'proofing'}:
                album.state = 'published'

    def action_mark_delivered(self):
        for album in self:
            if album.state not in {'published', 'delivered'}:
                continue
            album.state = 'delivered'

    def action_archive(self):
        self.write({'state': 'archived'})

    def unlink(self):
        if not self.env.context.get('skip_album_asset_cleanup'):
            assets_to_remove = self.env['tienda.foto.asset']
            for album in self:
                assets_to_remove |= album.asset_ids
            if assets_to_remove:
                assets_to_remove.sudo().unlink()
        return super().unlink()
