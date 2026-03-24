import secrets

from odoo import api, fields, models

from .utils import slugify_text


class TiendaFotoEvento(models.Model):
    _name = 'tienda.foto.evento'
    _description = 'Eventos de fotos'
    _inherit = ['mail.thread', 'mail.activity.mixin'] #para que se hereda esto? 
    # Se hereda para poder usar funcionalidades de seguimiento y actividades en el modelo por ejemplo, seguimiento de cambios en campos, asignación de tareas, etc.
    _order = 'fecha desc, id desc'

    name = fields.Char(string='Nombre', required=True)
    fecha = fields.Datetime(string='Fecha del Evento', required=True)
    ciudad = fields.Char(string='Ciudad')
    estado_provincia = fields.Char(string='Estado / Provincia')
    pais_id = fields.Many2one('res.country', string='País') # res.country es el modelo estándar de Odoo para países, que contiene la lista de países reconocidos internacionalmente.
    categoria_id = fields.Many2one(
        comodel_name='tienda.foto.categoria',
        string='Categoría',
        required=True,
        domain="[('display_on_homepage', '=', True), ('estado', '=', 'publicado'), ('website_published', '=', True)]"
    )
    photographer_id = fields.Many2one(
        comodel_name='res.partner',
        string='Fotógrafo',
        required=True,
        domain="[('is_photographer', '=', True)]" # Asegura que solo se puedan seleccionar socios que sean fotógrafos
    )
    plan_subscription_id = fields.Many2one(
        comodel_name='sale.subscription',
        string='Suscripción vinculada',
        compute='_compute_plan_subscription', 
        store=True,
        readonly=False
    )
    descripcion = fields.Html(string='Descripción') # Descripción del evento en formato HTML, que permite incluir texto, imágenes y otros elementos para detallar el evento
    image_cover = fields.Image(
        string='Portada del evento',
        max_width=1920,
        max_height=1080,
        attachment=True
    )
    precio_base = fields.Monetary(string='Precio base sugerido', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id.id)
    carpeta_externa = fields.Char(string='Carpeta/Álbum Externo')
    website_slug = fields.Char(string='Slug para web', required=True)
    portal_token = fields.Char(string='Token portal', copy=False)
    portal_url = fields.Char(string='URL pública', compute='_compute_portal_url')
    website_published = fields.Boolean(string='Publicado en web', default=False)
    estado = fields.Selection([
        ('borrador', 'Borrador'),
        ('produccion', 'En producción'),
        ('revision', 'En revisión'),
        ('publicado', 'Publicado'),
        ('archivado', 'Archivado')
    ], string='Estado', default='borrador')
    is_featured = fields.Boolean(string='Evento destacado')
    upload_token = fields.Char(string='Token de subida masiva')
    foto_ids = fields.One2many(
        comodel_name='tienda.foto.asset',
        inverse_name='evento_id',
        string='Fotos'
    )
    foto_count = fields.Integer(string='Cantidad de fotos', compute='_compute_foto_count')
    album_ids = fields.One2many('tienda.foto.album', 'event_id', string='Álbumes')
    album_count = fields.Integer(string='Álbumes generados', compute='_compute_album_count')
    customer_ids = fields.Many2many('res.partner', string='Clientes vinculados')
    customer_count = fields.Integer(string='Clientes', compute='_compute_customer_count')
    download_pin = fields.Char(string='PIN de descarga')
    delivery_deadline = fields.Date(string='Fecha límite de entrega')
    published_at = fields.Datetime(string='Publicado el')
    last_customer_activity = fields.Datetime(string='Última interacción')
    crm_lead_id = fields.Many2one('crm.lead', string='Oportunidad vinculada')
    crm_stage_id = fields.Many2one('crm.stage', related='crm_lead_id.stage_id', store=True, readonly=True)
    auto_publish = fields.Boolean(string='Auto publicar al subir fotos', default=True)
    lifecycle_state = fields.Selection([
        ('planning', 'Planificación'),
        ('shooting', 'Sesión en progreso'),
        ('editing', 'Edición'),
        ('proofing', 'Proofing con cliente'),
        ('selling', 'En venta'),
        ('completed', 'Completado'),
        ('archived', 'Archivado')
    ], string='Ciclo de vida', default='planning', tracking=True)

    _sql_constraints = [
        ('website_slug_unique', 'unique(website_slug)', 'Ya existe un evento con el mismo slug.'),
        ('portal_token_unique', 'unique(portal_token)', 'El token del evento debe ser único.'),
    ]

    @api.depends('foto_ids')
    def _compute_foto_count(self): 
        for event in self:
            event.foto_count = len(event.foto_ids)

    @api.depends('album_ids')
    def _compute_album_count(self):
        for event in self:
            event.album_count = len(event.album_ids)

    @api.depends('customer_ids')
    def _compute_customer_count(self): 
        for event in self:
            event.customer_count = len(event.customer_ids)

    @api.depends('photographer_id.plan_subscription_ids')
    def _compute_plan_subscription(self): # Vincula automáticamente la suscripción activa del fotógrafo al evento
        for event in self:
            if not event.photographer_id: # Si no hay fotógrafo asignado, no se puede vincular una suscripción
                event.plan_subscription_id = False
                continue
            if event.plan_subscription_id and event.plan_subscription_id.partner_id == event.photographer_id: # Mantener la suscripción si ya está vinculada correctamente
                continue
            active_subscription = event.photographer_id.plan_subscription_ids.filtered(
                lambda s: s.fotoapp_is_photographer_plan and s.state in {'trial', 'active', 'grace'}
            )[:1]
            event.plan_subscription_id = active_subscription.id if active_subscription else False

    @api.depends('portal_token')
    def _compute_portal_url(self): # Genera la URL pública del evento basada en el token
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for event in self:
            if event.portal_token:
                event.portal_url = f"{base_url}/fotoapp/event/{event.portal_token}"
            else:
                event.portal_url = False

    def _prepare_slug(self, value):
        base = value or (f"{self.name}-{self.id}" if (self.name and self.id) else self.name)
        return slugify_text(base, fallback='evento')

    @api.model_create_multi
    def create(self, vals_list): # Genera slugs, tokens de subida y portal al crear eventos
        for vals in vals_list:
            vals['website_slug'] = slugify_text(vals.get('website_slug') or vals.get('name'), fallback='evento')
        events = super().create(vals_list)
        events._ensure_upload_tokens()
        events._ensure_portal_tokens()
        return events

    def write(self, vals): # el write se usa para actualizar registros existentes, por ejemplo, cambiar el nombre o estado de un evento.
        if vals.get('website_slug'):
            vals['website_slug'] = slugify_text(vals['website_slug'], fallback='evento')
        res = super().write(vals)
        if {'website_slug', 'name'} & set(vals.keys()):
            self._ensure_upload_tokens()
        if 'portal_token' in vals and not vals['portal_token']:
            self._ensure_portal_tokens()
        return res

    def _ensure_upload_tokens(self): # Asegura que cada evento tenga un token de subida único
        for event in self.filtered(lambda e: not e.upload_token):
            fallback = slugify_text(f"{event.name}-{event.id}", fallback='evento') #el fallback es para asegurar que siempre haya un valor válido
            event.upload_token = self.env['ir.sequence'].next_by_code('tienda.foto.evento.upload') or fallback

    def _ensure_portal_tokens(self):
        for event in self.filtered(lambda e: not e.portal_token):
            event.portal_token = secrets.token_urlsafe(16)

    def action_publicar(self):
        self.write({
            'estado': 'publicado',
            'lifecycle_state': 'selling',
            'website_published': True,
            'published_at': fields.Datetime.now(),
        })

    def action_archivar(self):
        self.write({
            'estado': 'archivado',
            'lifecycle_state': 'archived',
            'website_published': False,
        })

    def action_volver_borrador(self):
        self.write({
            'estado': 'borrador',
            'lifecycle_state': 'planning',
            'website_published': False,
        })

    def action_next_stage(self):
        stage_flow = {
            'planning': 'shooting',
            'shooting': 'editing',
            'editing': 'proofing',
            'proofing': 'selling',
            'selling': 'completed',
            'completed': 'archived',
        }
        for event in self:
            next_stage = stage_flow.get(event.lifecycle_state)
            if next_stage:
                event.lifecycle_state = next_stage

    def unlink(self):
        Asset = self.env['tienda.foto.asset'].sudo()
        assets = Asset.search([('evento_id', 'in', self.ids)])
        if assets:
            assets.unlink()
        albums = self.mapped('album_ids').sudo()
        if albums:
            albums.with_context(skip_album_asset_cleanup=True).unlink()
        return super().unlink()