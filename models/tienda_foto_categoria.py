from odoo import api, fields, models

from .utils import slugify_text


class TiendaFotoCategoria(models.Model):
    _name = 'tienda.foto.categoria'
    _description = 'Categorías de fotos'
    _order = 'sequence, name'

    name = fields.Char(string='Nombre', required=True)
    description = fields.Text(string='Descripción interna')
    website_description = fields.Html(string='Descripción para el sitio web')
    sequence = fields.Integer(string='Secuencia', default=10)
    color = fields.Integer(string='Color')
    image_cover = fields.Image(
        string='Imagen de portada',
        max_width=1920,
        max_height=1080,
        attachment=True,
        help='Imagen mostrada en tarjetas de la web.'
    )
    slug = fields.Char(string='Slug', required=True)
    estado = fields.Selection([
        ('borrador', 'Borrador'),
        ('publicado', 'Publicado'),
        ('archivado', 'Archivado')
    ], string='Estado', default='borrador')
    website_published = fields.Boolean(string='Publicado en web', default=False)
    display_on_homepage = fields.Boolean(string='Mostrar en home', default=False)
    portal_sequence = fields.Integer(string='Orden en portal', default=10)
    is_system_category = fields.Boolean(string='Categoría del sistema', default=False)
    evento_ids = fields.One2many(
        comodel_name='tienda.foto.evento',
        inverse_name='categoria_id',
        string='Eventos'
    )
    event_count = fields.Integer(
        string='Total de eventos',
        compute='_compute_event_metrics',
        store=True,
    )
    website_event_count = fields.Integer(
        string='Eventos publicados en web',
        compute='_compute_event_metrics',
        store=True,
    )

    _sql_constraints = [
        ('slug_unique', 'unique(slug)', 'El slug debe ser único.'),
    ]

    def action_mark_system(self):
        self.write({'is_system_category': True})

    @api.depends('evento_ids', 'evento_ids.estado', 'evento_ids.website_published')
    def _compute_event_metrics(self):
        for record in self:
            events = record.evento_ids
            record.event_count = len(events)
            record.website_event_count = len(
                events.filtered(lambda event: event.website_published and event.estado == 'publicado')
            )

    def _prepare_slug(self, value):
        slug_base = value or self.name or ''
        return slugify_text(slug_base, fallback='categoria')

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        to_create = []
        for vals in vals_list:
            vals = dict(vals)
            vals['slug'] = self._prepare_slug(vals.get('slug') or vals.get('name'))
            existing = False
            if vals.get('is_system_category'):
                existing = self.search([('slug', '=', vals['slug'])], limit=1)
            if existing:
                existing.write(vals)
                records |= existing
            else:
                to_create.append(vals)
        if to_create:
            records |= super().create(to_create)
        return records

    def write(self, vals):
        if vals.get('slug'):
            vals['slug'] = self._prepare_slug(vals['slug'])
        return super().write(vals)

    def action_publicar(self):
        self.write({'estado': 'publicado', 'website_published': True})

    def action_archivar(self):
        self.write({'estado': 'archivado', 'website_published': False})

    def action_volver_borrador(self):
        self.write({'estado': 'borrador'})